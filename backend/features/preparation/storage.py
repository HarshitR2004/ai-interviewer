"""Only Markdown and the original PDF are persisted. No generated-data sidecars."""

import re
from collections.abc import Callable
from pathlib import Path
from threading import RLock
from typing import TypeVar

from backend.common.errors import Conflict, NotFound, Unavailable
from backend.common.files import atomic_write, run_io

from .documents import parse_plan, parse_profile, render_plan, render_profile
from .models import Preparation

T = TypeVar("T")


class MarkdownPreparationStore:
    def __init__(self, root: Path):
        self.root = root
        self._lock = RLock()

    def _path(self, candidate_id: str) -> Path:
        # Restrict candidate IDs before using them as directory names.
        if not re.fullmatch(r"[a-f0-9]{32}", candidate_id):
            raise NotFound("Candidate not found.")
        return self.root / candidate_id

    async def _io(self, work: Callable[[], T]) -> T:
        # Serialize filesystem work off the event loop and translate storage failures.
        def locked() -> T:
            with self._lock:
                try:
                    return work()
                except FileNotFoundError as exc:
                    raise NotFound(
                        "Completed preparation not found; both Markdown documents are required."
                    ) from exc
                except OSError as exc:
                    raise Unavailable("Preparation documents could not be read or saved.") from exc

        return await run_io(locked)

    async def create(self, preparation: Preparation, resume: bytes) -> None:
        # Persist the original resume and both generated documents for a new candidate.
        def write() -> None:
            path = self._path(preparation.candidate_id)
            if path.exists():
                raise Conflict("Candidate already exists.")
            path.mkdir(parents=True)
            atomic_write(path / "resume.pdf", resume)
            atomic_write(path / "persona.md", render_profile(preparation.profile))
            atomic_write(
                path / "interview-plan.md",
                render_plan(preparation.plan, preparation.settings, preparation.job_description),
            )

        await self._io(write)

    async def load(self, candidate_id: str) -> Preparation:
        # Reconstruct preparation from both Markdown documents without calling the model.
        def read() -> Preparation:
            path = self._path(candidate_id)
            profile = parse_profile((path / "persona.md").read_text(encoding="utf-8"))
            plan, settings, jd = parse_plan(
                (path / "interview-plan.md").read_text(encoding="utf-8"), profile
            )
            return Preparation(
                candidate_id=candidate_id,
                profile=profile,
                plan=plan,
                settings=settings,
                job_description=jd,
            )

        return await self._io(read)

    async def replace_plan(self, preparation: Preparation) -> None:
        # Atomically replace a completed plan while preserving the saved profile.
        def write() -> None:
            path = self._path(preparation.candidate_id)
            if not (path / "persona.md").is_file() or not (path / "interview-plan.md").is_file():
                raise NotFound("Completed preparation not found.")
            atomic_write(
                path / "interview-plan.md",
                render_plan(preparation.plan, preparation.settings, preparation.job_description),
            )

        await self._io(write)
