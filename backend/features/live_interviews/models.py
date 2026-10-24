from typing import Literal

from pydantic import Field, model_validator

from backend.shared.models import Record


class CreateSession(Record):
    candidate_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    event_id: str = Field(min_length=1, max_length=128)


class AnswerEvent(Record):
    event_id: str = Field(min_length=1, max_length=128)
    prompt_id: str = Field(min_length=1, max_length=128)
    answer: str = Field(min_length=1, max_length=16000)
    replaces_event_id: str | None = Field(default=None, min_length=1, max_length=128)

    @model_validator(mode="after")
    def substantive(self):
        if not self.answer.strip():
            raise ValueError("Answer cannot be blank.")
        return self


class EndEvent(Record):
    event_id: str = Field(min_length=1, max_length=128)


class Decision(Record):
    action: Literal["clarify", "follow_up", "advance", "finish"]
    evidence: list[str] = Field(default_factory=list, max_length=20)
    missing_evidence: list[str] = Field(default_factory=list, max_length=20)
    next_question: str | None = Field(default=None, min_length=1, max_length=2000)

    @model_validator(mode="after")
    def needs_prompt(self):
        if self.action in {"clarify", "follow_up"} and not (
            self.next_question and self.next_question.strip()
        ):
            raise ValueError("A clarification or follow-up requires question text.")
        return self


class EngineError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
