from pydantic import Field

from backend.shared.models import Record


class Project(Record):
    id: str
    name: str
    purpose: str
    technologies: list[str]
    contributions: list[str]
    technical_details: list[str]
    source_refs: list[str]


class Persona(Record):
    name: str
    background: str
    education: list[str]
    experience: list[str]
    skills: dict[str, list[str]]
    projects: list[Project] = Field(max_length=6)
    discussion_topics: list[str] = Field(max_length=8)
    source_references: list[str]
    collection_status: dict[str, str]
