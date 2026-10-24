"""Validate untrusted resume PDFs before persistence or model processing."""

import json
import os
import re
import subprocess
import sys
from io import BytesIO
from pathlib import Path
from threading import BoundedSemaphore
from urllib.parse import urlsplit

from backend.shared.errors import WorkflowError

MAX_PDF_BYTES = 10 * 1024 * 1024
MAX_TEXT_CHARS = 24000
PARSER_TIMEOUT_SECONDS = 10
_PARSER_SLOTS = BoundedSemaphore(2)
_INVALID = "This PDF could not be safely read. Please upload a plain text-based PDF."
_ACTIVE = "PDF scripts, automatic actions, forms, and embedded files are not accepted."
_BLOCKED_KEYS = {
    "/JavaScript",
    "/JS",
    "/OpenAction",
    "/AA",
    "/AcroForm",
    "/XFA",
    "/EmbeddedFiles",
    "/EmbeddedFile",
    "/EF",
    "/AF",
    "/RichMedia",
    "/RichMediaContent",
    "/Movie",
    "/Sound",
    "/3D",
    "/Collection",
}
_BLOCKED_ACTIONS = {
    "/JavaScript",
    "/Launch",
    "/SubmitForm",
    "/ImportData",
    "/GoToR",
    "/GoToE",
    "/Rendition",
    "/Movie",
    "/Sound",
    "/Hide",
    "/ResetForm",
    "/SetOCGState",
}


def _check_envelope(content: bytes) -> None:
    if not content or len(content) > MAX_PDF_BYTES:
        raise WorkflowError("Please upload a PDF of at most 10 MB.")
    if not re.match(rb"%PDF-(?:1\.[0-7]|2\.0)(?:\r\n|\r|\n)", content):
        raise WorkflowError("Please upload a valid PDF resume.")
    if not content.rstrip(b" \t\r\n").endswith(b"%%EOF"):
        raise WorkflowError(_INVALID)


def _check_objects(reader) -> None:
    from pypdf.generic import ArrayObject, DictionaryObject, IndirectObject

    references = {
        (number, generation)
        for generation, entries in reader.xref.items()
        if generation != 65535
        for number in entries
        if number != 0
    }
    references.update((number, 0) for number in reader.xref_objStm)
    if len(references) > 10000:
        raise WorkflowError("This PDF is too complex to process safely.")
    stack = [reader.trailer]
    stack.extend(IndirectObject(number, generation, reader) for number, generation in references)
    seen_refs, seen_objects = set(), set()
    visited = 0
    while stack:
        visited += 1
        if visited > 100000:
            raise WorkflowError("This PDF is too complex to process safely.")
        value = stack.pop()
        if isinstance(value, IndirectObject):
            key = (value.idnum, value.generation)
            if key in seen_refs:
                continue
            seen_refs.add(key)
            value = value.get_object()
        if not isinstance(value, (DictionaryObject, ArrayObject)):
            continue
        if id(value) in seen_objects:
            continue
        seen_objects.add(id(value))
        if isinstance(value, DictionaryObject):
            if _BLOCKED_KEYS.intersection(value):
                raise WorkflowError(_ACTIVE)
            if value.get("/Type") in {"/EmbeddedFile", "/Filespec", "/RichMedia", "/3D"}:
                raise WorkflowError(_ACTIVE)
            action = value.get("/S")
            if action in _BLOCKED_ACTIONS or (
                value.get("/Type") == "/Action" and action not in {"/URI", "/GoTo"}
            ):
                raise WorkflowError(_ACTIVE)
            if "/URI" in value:
                uri = value["/URI"]
                if not isinstance(uri, str) or urlsplit(uri).scheme.lower() not in {
                    "https",
                    "http",
                    "mailto",
                }:
                    raise WorkflowError("This PDF contains an unsupported link action.")
            stack.extend(value.values())
        else:
            stack.extend(value)


def _extract_checked(content: bytes) -> str:
    from pypdf import PdfReader, apply_configuration

    _check_envelope(content)
    try:
        with apply_configuration(
            maximum_declared_stream_length=8 * 1024 * 1024,
            array_based_stream_maximum_output_length=8 * 1024 * 1024,
            zlib_maximum_output_length=8 * 1024 * 1024,
            lzw_maximum_output_length=8 * 1024 * 1024,
            run_length_maximum_output_length=8 * 1024 * 1024,
            stream_decoding_work_maximum_length=16 * 1024 * 1024,
            stream_parsing_work_maximum_count=100000,
            stream_filters_maximum_length=4,
            array_maximum_element_count=10000,
            dictionary_maximum_element_count=10000,
            page_tree_maximum_entries=100,
            page_tree_maximum_depth=10,
            xform_maximum_invocations_per_extraction=100,
        ):
            reader = PdfReader(BytesIO(content), strict=True, root_object_recovery_limit=100)
            if reader.is_encrypted:
                raise WorkflowError("Please upload a PDF without password protection.")
            _check_objects(reader)
            if not 1 <= len(reader.pages) <= 20:
                raise WorkflowError("Please use a resume with 1 to 20 pages.")
            parts, length = [], 0
            for page in reader.pages:
                text = page.extract_text() or ""
                length += len(text) + (2 if parts else 0)
                if length > MAX_TEXT_CHARS:
                    raise WorkflowError("This resume is too long. Please upload a shorter version.")
                parts.append(text)
            text = "\n\n".join(parts).strip()
    except WorkflowError:
        raise
    except Exception:
        raise WorkflowError(_INVALID) from None
    if len(text) < 40:
        raise WorkflowError("This resume has no readable text. Please upload a text-based PDF.")
    return text


def extract_resume(content: bytes) -> str:
    """Run parsing out of process so a timeout terminates parser work, not just its waiter.

    This is resource containment, not an antivirus or an OS security sandbox.
    """
    _check_envelope(content)
    if not _PARSER_SLOTS.acquire(blocking=False):
        raise WorkflowError("Resume processing is busy. Please try again shortly.")
    try:
        # Do not inherit provider credentials or Python import-path overrides.
        env = {
            key: value
            for key, value in os.environ.items()
            if key.upper() in {"SYSTEMROOT", "WINDIR", "TEMP", "TMP", "LANG", "LC_ALL"}
        }
        result = subprocess.run(
            [sys.executable, "-m", "backend.features.collection.resume", "--worker"],
            input=content,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=PARSER_TIMEOUT_SECONDS,
            check=False,
            env=env,
            cwd=Path(__file__).resolve().parents[3],
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        if result.returncode or len(result.stdout) > 6 * MAX_TEXT_CHARS + 1024:
            raise WorkflowError(_INVALID)
        payload = json.loads(result.stdout)
        if "error" in payload:
            raise WorkflowError(payload["error"])
        return payload["text"]
    except subprocess.TimeoutExpired:
        raise WorkflowError(
            "This PDF took too long to process. Please upload a simpler copy."
        ) from None
    except (OSError, ValueError, KeyError, TypeError):
        raise WorkflowError(_INVALID) from None
    finally:
        _PARSER_SLOTS.release()


def _worker() -> None:
    if os.name == "posix":
        import resource

        resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024, 512 * 1024 * 1024))
        resource.setrlimit(resource.RLIMIT_CPU, (8, 8))
    try:
        payload = {"text": _extract_checked(sys.stdin.buffer.read(MAX_PDF_BYTES + 1))}
    except WorkflowError as exc:
        payload = {"error": str(exc)}
    except Exception:
        payload = {"error": _INVALID}
    sys.stdout.buffer.write(json.dumps(payload).encode("utf-8"))


if __name__ == "__main__" and sys.argv[1:] == ["--worker"]:
    _worker()
