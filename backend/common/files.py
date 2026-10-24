import asyncio
import os
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import ParamSpec, TypeVar

P = ParamSpec("P")
T = TypeVar("T")


async def run_io(operation: Callable[P, T], *args: P.args, **kwargs: P.kwargs) -> T:
    """Do not release process ownership while a cancelled file/SQL write still runs."""
    task = asyncio.create_task(asyncio.to_thread(operation, *args, **kwargs))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        await task
        raise


def atomic_write(path: Path, content: str | bytes) -> None:
    # Flush a sibling temporary file before atomically replacing the destination.
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
