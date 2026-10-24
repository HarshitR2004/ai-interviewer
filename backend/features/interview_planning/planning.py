import re
from typing import Any, Literal, cast

from pydantic import BaseModel, create_model

from backend.common.errors import InvalidInput

from .models import InterviewPlan, InterviewSettings, Section


def explicit_competencies(job_description: str) -> list[str] | None:
    match = re.search(r"(?im)^\s*required competencies:\s*([^\r\n]+)", job_description)
    if not match:
        return None
    values = [part.strip(" .;") for part in re.split(r"[,;]", match.group(1))]
    values = list(dict.fromkeys(value for value in values if value))
    if not 1 <= len(values) <= 6:
        raise InvalidInput("Please list between one and six required competencies.")
    return values


def planning_schema(competencies: list[str]) -> type[BaseModel]:
    fields: dict[str, Any] = {}
    for index, competency in enumerate(competencies, start=1):
        section = create_model(
            f"RequiredSection{index}",
            __base__=Section,
            competency=(cast(Any, Literal[competency]), ...),
        )
        fields[f"section_{index}"] = (section, ...)
    sections = create_model("RequiredSections", **fields)
    return create_model("PreparedInterview", role=(str, ...), sections=(sections, ...))


def as_interview(value: BaseModel, competencies: list[str]) -> InterviewPlan:
    return InterviewPlan(
        role=value.model_dump()["role"],
        required_competencies=competencies,
        sections=list(value.model_dump()["sections"].values()),
    )


def allocate_time(plan: InterviewPlan, settings: InterviewSettings) -> None:
    total = sum(section.minutes for section in plan.sections)
    if total == settings.duration:
        return
    count = len(plan.sections)
    if count > settings.duration:
        raise ValueError("There are too many sections for this interview duration.")
    remaining = settings.duration - count
    shares = [remaining * section.minutes / total for section in plan.sections]
    allocations = [1 + int(share) for share in shares]
    leftover = settings.duration - sum(allocations)
    order = sorted(range(count), key=lambda index: shares[index] % 1, reverse=True)
    for index in order[:leftover]:
        allocations[index] += 1
    for section, minutes in zip(plan.sections, allocations, strict=True):
        section.minutes = minutes
