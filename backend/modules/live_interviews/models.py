from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.modules.pre_interview.preparation.models import Preparation, Question, Section

Action = Literal["clarify", "follow_up", "advance", "finish"]


class CreateSession(BaseModel):
    model_config = ConfigDict(extra="forbid")
    candidate_id: str = Field(pattern=r"^[a-f0-9]{32}$")


class Decision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Action
    intent: Literal["answer", "repeat", "clarification", "stop"] = "answer"
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


class PublicPrompt(BaseModel):
    id: str
    question_id: str
    text: str


class Prompt(PublicPrompt):
    pass


class TransitionExplanation(BaseModel):
    proposed_action: Action
    executed_action: Action
    reason: str
    assessment_available: bool


class PublicSession(BaseModel):
    session_id: str
    candidate_id: str
    status: Literal["waiting", "active", "completed", "failed"]
    current_prompt: PublicPrompt | None
    question_number: int
    question_count: int
    follow_up_count: int
    deadline_at: float
    progression: list[TransitionExplanation]
    completion_reason: str | None = None
    last_turn_id: str | None = None


class AnswerResult(BaseModel):
    session: PublicSession
    transition: TransitionExplanation | None = None
    spoken_text: str = ""


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
    status: Literal["waiting", "active", "completed", "failed"] = "waiting"
    revision: int = 0
    ready: bool = False
    agent_seen_at: float | None = None
    ended_at: float | None = None
    disconnected_at: float | None = None
    completion_reason: str | None = None
    pending_turn: str | None = None
    turn_results: dict[str, AnswerResult] = Field(default_factory=dict)
    history: list[dict[str, str | float | bool]] = Field(default_factory=list)
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
            current_prompt=(
                PublicPrompt.model_validate(self.current_prompt.model_dump())
                if self.current_prompt
                else None
            ),
            question_number=self.question_index + 1,
            question_count=len(self.preparation.plan.sections),
            follow_up_count=self.follow_up_count,
            deadline_at=self.deadline_at,
            progression=self.progression,
            completion_reason=self.completion_reason,
            last_turn_id=next(reversed(self.turn_results), None),
        )


class TurnInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    prompt_id: str = Field(min_length=1, max_length=128)
    turn_id: str = Field(min_length=1, max_length=128)
    text: str = Field(min_length=1, max_length=16000)


class AgentEvent(BaseModel):
    kind: Literal["ready", "joined", "disconnected", "invalidate", "failed", "playback"]
    prompt_id: str | None = None
    text: str = Field(default="", max_length=4000)
    interrupted: bool = False
