from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.features.interview_planning.models import Question, Section
from backend.features.preparation.models import Preparation
from backend.integrations.speech.contracts import Transcript

Action = Literal["clarify", "follow_up", "advance", "finish"]


class CreateSession(BaseModel):
    model_config = ConfigDict(extra="forbid")
    candidate_id: str = Field(pattern=r"^[a-f0-9]{32}$")


class AnswerInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    prompt_id: str = Field(min_length=1, max_length=128)
    answer: str = Field(min_length=1, max_length=16000)

    @model_validator(mode="after")
    def substantive(self) -> "AnswerInput":
        if not self.answer.strip():
            raise ValueError("Answer cannot be blank.")
        return self


class Decision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Action
    evidence: list[str] = Field(default_factory=list, max_length=20)
    missing_evidence: list[str] = Field(default_factory=list, max_length=20)
    next_question: str | None = Field(default=None, min_length=1, max_length=2000)

    @model_validator(mode="after")
    def needs_question(self) -> "Decision":
        if self.action in {"clarify", "follow_up"} and not (
            self.next_question and self.next_question.strip()
        ):
            raise ValueError("A clarification or follow-up requires question text.")
        return self


class Prompt(BaseModel):
    id: str
    question_id: str
    text: str


class TransitionExplanation(BaseModel):
    proposed_action: Action
    executed_action: Action
    reason: str
    assessment_available: bool


class PublicSession(BaseModel):
    session_id: str
    candidate_id: str
    status: Literal["active", "completed"]
    current_prompt: Prompt | None
    question_number: int
    question_count: int
    follow_up_count: int
    deadline_at: float
    progression: list[TransitionExplanation]


class AnswerResult(BaseModel):
    session: PublicSession
    transition: TransitionExplanation
    transcription: Transcript | None = None


class AnswerTurn(BaseModel):
    question_id: str
    answer: str


class Evidence(BaseModel):
    question_id: str
    evidence: list[str]
    missing_evidence: list[str]


class SessionState(BaseModel):
    session_id: str
    preparation: Preparation
    status: Literal["active", "completed"] = "active"
    question_index: int = 0
    follow_up_count: int = 0
    used_prepared_followups: list[str] = Field(default_factory=list)
    section_started_at: float
    deadline_at: float
    current_prompt: Prompt | None
    answers: list[AnswerTurn] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    progression: list[TransitionExplanation] = Field(default_factory=list)

    @property
    def section(self) -> Section:
        return self.preparation.plan.sections[self.question_index]

    @property
    def question(self) -> Question:
        return self.section.questions[0]

    @property
    def question_id(self) -> str:
        return f"s{self.question_index + 1}q1"

    def public(self) -> PublicSession:
        return PublicSession(
            session_id=self.session_id,
            candidate_id=self.preparation.candidate_id,
            status=self.status,
            current_prompt=self.current_prompt,
            question_number=self.question_index + 1,
            question_count=len(self.preparation.plan.sections),
            follow_up_count=self.follow_up_count,
            deadline_at=self.deadline_at,
            progression=self.progression,
        )
