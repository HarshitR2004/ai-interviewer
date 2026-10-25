"""Atomic local text history; never stores audio."""

import json
import re
from pathlib import Path

from backend.common.errors import NotFound

from .models import SessionState


class JsonHistoryStore:
    def __init__(self, directory: Path):
        self.directory = directory

    def save(self, state: SessionState) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        target = self.directory / f"{state.session_id}.json"
        temporary = target.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(
                {
                    "session": state.public().model_dump(),
                    "events": state.history,
                    "evidence": [item.model_dump() for item in state.evidence],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        temporary.replace(target)

    def load(self, session_id: str) -> dict[str, object]:
        if not re.fullmatch(r"[a-f0-9]{32}", session_id):
            raise NotFound("Interview history not found.")
        try:
            value: dict[str, object] = json.loads(
                (self.directory / f"{session_id}.json").read_text(encoding="utf-8")
            )
            return value
        except FileNotFoundError as exc:
            raise NotFound("Interview history not found.") from exc
