from pydantic import BaseModel, ConfigDict, Field


class Project(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    name: str
    purpose: str
    technologies: list[str]
    contributions: list[str]
    technical_details: list[str]
    source_refs: list[str]


class CandidateProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    background: str
    education: list[str]
    experience: list[str]
    skills: dict[str, list[str]]
    projects: list[Project] = Field(max_length=6)
    discussion_topics: list[str] = Field(max_length=8)
    source_references: list[str]
    collection_status: dict[str, str]
