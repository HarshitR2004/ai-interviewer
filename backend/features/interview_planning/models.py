from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class InterviewSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    duration: int = Field(default=45, ge=15, le=120)
    seniority: Literal["junior", "mid", "senior"] = "junior"
    interview_type: Literal["mixed", "technical", "project"] = "mixed"


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
    follow_ups: list[str] = Field(min_length=1)
    strong_answer_signals: list[str] = Field(min_length=1)
    scoring_guidance: ScoringGuidance


class Section(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str
    competency: str = Field(description="An exact copy of one entry in required_competencies.")
    minutes: int = Field(ge=1)
    questions: list[Question] = Field(min_length=1, max_length=1)


class InterviewPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: str
    required_competencies: list[str] = Field(
        min_length=1, description="Every entry must appear verbatim as a section's competency."
    )
    sections: list[Section] = Field(min_length=1)
