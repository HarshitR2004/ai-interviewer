import json
import os
import subprocess
import sys
from pathlib import Path
from threading import BoundedSemaphore

from backend.common.errors import InvalidInput

from .pdf_validation import (
    _INVALID,
    MAX_TEXT_CHARS,
    PARSER_TIMEOUT_SECONDS,
    _check_envelope,
)

_PARSER_SLOTS = BoundedSemaphore(2)


def extract_resume(content: bytes) -> str:
    """Run parsing out of process so a timeout terminates parser work, not just its waiter.

    This is resource containment, not an antivirus or an OS security sandbox.
    """
    _check_envelope(content)
    if not _PARSER_SLOTS.acquire(blocking=False):
        raise InvalidInput("Resume processing is busy. Please try again shortly.")
    try:
        # Do not inherit provider credentials or Python import-path overrides.
        env = {
            key: value
            for key, value in os.environ.items()
            if key.upper() in {"SYSTEMROOT", "WINDIR", "TEMP", "TMP", "LANG", "LC_ALL"}
        }
        creation_flags = 0
        if sys.platform == "win32":
            creation_flags = subprocess.CREATE_NO_WINDOW
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "backend.features.resume_ingestion.pdf_worker",
                "--worker",
            ],
            input=content,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=PARSER_TIMEOUT_SECONDS,
            check=False,
            env=env,
            cwd=Path(__file__).resolve().parents[3],
            creationflags=creation_flags,
        )
        if result.returncode or len(result.stdout) > 6 * MAX_TEXT_CHARS + 1024:
            raise InvalidInput(_INVALID)
        payload = json.loads(result.stdout)
        if "error" in payload:
            raise InvalidInput(payload["error"])
        text = payload["text"]
        if not isinstance(text, str):
            raise InvalidInput(_INVALID)
        return text
    except subprocess.TimeoutExpired:
        raise InvalidInput(
            "This PDF took too long to process. Please upload a simpler copy."
        ) from None
    except (OSError, ValueError, KeyError, TypeError):
        raise InvalidInput(_INVALID) from None
    finally:
        _PARSER_SLOTS.release()


class PdfExtractor:
    def extract(self, content: bytes) -> str:
        return extract_resume(content)
