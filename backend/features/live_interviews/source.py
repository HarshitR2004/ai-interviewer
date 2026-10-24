import json
import re
from pathlib import Path

from pydantic import ValidationError

from backend.features.interviews.models import InterviewPlan, InterviewSettings

from .models import EngineError
from .storage import digest


class LocalPlanSource:
    """Read preparation artifacts through one explicit, read-only boundary."""

    def __init__(self, root: Path, active: set[str]):
        self.root = root
        self.active = active

    async def load(self, candidate_id: str) -> dict:
        if candidate_id in self.active:
            raise EngineError(409, "Preparation is still running.")

        def read():
            if not re.fullmatch(r"[a-f0-9]{32}", candidate_id):
                raise EngineError(404, "Candidate not found.")
            path = self.root / candidate_id
            try:
                status = json.loads((path / "status.json").read_text(encoding="utf-8"))
                if status["state"] != "completed":
                    raise EngineError(409, "A completed preparation is required.")
                plan = InterviewPlan.model_validate_json(
                    (path / "structured/interview.json").read_text(encoding="utf-8")
                )
                settings = InterviewSettings.model_validate_json(
                    (path / "inputs/settings.json").read_text(encoding="utf-8")
                )
            except FileNotFoundError as exc:
                raise EngineError(404, "Completed interview plan not found.") from exc
            except (ValidationError, ValueError, KeyError) as exc:
                raise EngineError(409, "Saved preparation is invalid; prepare it again.") from exc
            if sum(section.minutes for section in plan.sections) != settings.duration:
                raise EngineError(409, "Saved plan and settings have inconsistent durations.")
            source = {"plan": plan.model_dump(), "settings": settings.model_dump()}
            source["plan_version"] = digest(source)
            return source

        # No await inside the read: the single-process preparation coordinator
        # cannot start a replan between the active check and artifact snapshot.
        return read()
