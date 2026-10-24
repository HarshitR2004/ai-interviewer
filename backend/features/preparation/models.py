from typing import Literal

from pydantic import Field

from backend.shared.models import Record


class Status(Record):
    candidate_id: str
    state: Literal["queued", "collecting", "profiling", "planning", "completed", "failed"]
    message: str
    warnings: list[str] = Field(default_factory=list)
