from pydantic import BaseModel, ConfigDict, Field

from backend.modules.pre_interview.interview_planning.models import InterviewPlan, InterviewSettings
from backend.modules.pre_interview.profiles.models import CandidateProfile


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
