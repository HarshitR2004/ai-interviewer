import json
import os
import tempfile
from pathlib import Path


def atomic_write(path: Path, content: str | bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = content.encode("utf-8") if isinstance(content, str) else content
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".pending-")
    try:
        with os.fdopen(fd, "wb") as file:
            file.write(payload)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def write_json(path: Path, content: dict) -> None:
    atomic_write(path, json.dumps(content, ensure_ascii=False, indent=2))
