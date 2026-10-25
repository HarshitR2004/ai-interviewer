from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from backend.modules.pre_interview.profiles.models import CandidateProfile

QuestionKind = Literal[
    "introduction",
    "project_overview",
    "experience_overview",
    "fundamentals",
    "framework",
    "project_detail",
    "role_scenario",
    "behavioral",
    "closing",
]


class InterviewSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    duration: int = Field(default=45, ge=15, le=120)
    seniority: Literal["junior", "mid", "senior"] = "junior"


class RoleRequirements(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: str
    competencies: list[str] = Field(min_length=1, max_length=6)


class ScoringGuidance(BaseModel):
    model_config = ConfigDict(extra="forbid")
    weak: str = Field(min_length=10, description="What earns 1 out of 5.")
    adequate: str = Field(min_length=10, description="What earns 3 out of 5.")
    strong: str = Field(min_length=10, description="What earns 5 out of 5.")


class Question(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str = Field(min_length=10)
    candidate_context: str
    project_id: str | None
    follow_ups: list[str] = Field(default_factory=list)
    strong_answer_signals: list[str] = Field(default_factory=list)
    scoring_guidance: ScoringGuidance | None = None


class Section(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str
    competency: str = Field(
        description="Primary role competency, or Introduction/Closing for context."
    )
    kind: QuestionKind = "fundamentals"
    covered_competencies: list[str] = Field(default_factory=list)
    minutes: int = Field(ge=1)
    questions: list[Question] = Field(min_length=1, max_length=1)

    @property
    def scored(self) -> bool:
        return self.kind not in {"introduction", "closing"}


class InterviewPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: str
    format_version: Literal[1, 2] = 1
    required_competencies: list[str] = Field(
        min_length=1, description="Every entry must be covered by at least one assessed section."
    )
    sections: list[Section] = Field(min_length=1)


class PreparationInputs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    job_description: str = Field(min_length=40, max_length=12000)
    settings: InterviewSettings = Field(default_factory=InterviewSettings)


class Preparation(BaseModel):
    candidate_id: str
    profile: CandidateProfile
    plan: InterviewPlan
    settings: InterviewSettings
    job_description: str
