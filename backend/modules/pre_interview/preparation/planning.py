import re
from typing import Any, Literal, cast

from pydantic import BaseModel, create_model

from backend.common.errors import InvalidInput
from backend.integrations.llm.contracts import StructuredGenerator
from backend.modules.pre_interview.profiles.models import CandidateProfile

from .blueprint import interview_flow
from .models import InterviewPlan, InterviewSettings, RoleRequirements, Section
from .prompts import PLANNER, ROLE_REQUIREMENTS
from .validation import validate_plan


def explicit_competencies(job_description: str) -> list[str] | None:
    # Honor a declared competency list before asking the model to extract one.
    match = re.search(r"(?im)^\s*required competencies:\s*([^\r\n]+)", job_description)
    if not match:
        return None
    values = [part.strip(" .;") for part in re.split(r"[,;]", match.group(1))]
    values = list(dict.fromkeys(value for value in values if value))
    if not 1 <= len(values) <= 6:
        raise InvalidInput("Please list between one and six required competencies.")
    return values


def planning_schema(
    competencies: list[str], settings: InterviewSettings | None = None, has_projects: bool = True
) -> type[BaseModel]:
    # Fix the conversational mix, allowing one topic to assess several role competencies.
    allowed = Literal[tuple(competencies)]  # type: ignore[valid-type]
    fields: dict[str, Any] = {}
    for index, kind in enumerate(interview_flow(settings or InterviewSettings(), has_projects), 1):
        primary = (
            Literal["Introduction"]
            if kind == "introduction"
            else (Literal["Closing"] if kind == "closing" else allowed)
        )
        section = create_model(
            f"RequiredSection{index}",
            __base__=Section,
            kind=(cast(Any, Literal[kind]), ...),
            competency=(cast(Any, primary), ...),
            covered_competencies=(cast(Any, list[allowed]), ...),  # type: ignore[valid-type]
        )
        fields[f"section_{index}"] = (section, ...)
    sections = create_model("RequiredSections", **fields)
    return create_model("PreparedInterview", role=(str, ...), sections=(sections, ...))


def as_interview(value: BaseModel, competencies: list[str]) -> InterviewPlan:
    # Convert schema-specific section fields into the domain plan format.
    data = value.model_dump()
    return InterviewPlan(
        role=data["role"],
        format_version=2,
        required_competencies=competencies,
        sections=list(data["sections"].values()),
    )


def allocate_time(plan: InterviewPlan, settings: InterviewSettings) -> None:
    # Fit model-proposed proportions to the requested duration, with at least one minute per section.
    if plan.format_version == 2:
        # Keep context short instead of letting model-proposed weights consume the interview.
        context_minutes = 1 if settings.duration <= 30 else 2
        for section in plan.sections:
            if not section.scored:
                section.minutes = context_minutes
        assessed = [section for section in plan.sections if section.scored]
        budget = settings.duration - sum(s.minutes for s in plan.sections if not s.scored)
        if not assessed or budget < len(assessed):
            raise ValueError("The interview must leave time for its assessed conversation topics.")
        weights = {"project_detail": 4, "behavioral": 2}
        total_weight = sum(weights.get(s.kind, 3) for s in assessed)
        shares = [
            (budget - len(assessed)) * weights.get(s.kind, 3) / total_weight for s in assessed
        ]
        allocations = [1 + int(share) for share in shares]
        order = sorted(range(len(assessed)), key=lambda i: shares[i] % 1, reverse=True)
        for index in order[: budget - sum(allocations)]:
            allocations[index] += 1
        for section, minutes in zip(assessed, allocations, strict=True):
            section.minutes = minutes
        return
    total = sum(section.minutes for section in plan.sections)
    if total == settings.duration:
        return
    count = len(plan.sections)
    if count > settings.duration:
        raise ValueError("There are too many sections for this interview duration.")
    # Reserve one minute per section, then distribute leftover minutes by fractional share.
    remaining = settings.duration - count
    shares = [remaining * section.minutes / total for section in plan.sections]
    allocations = [1 + int(share) for share in shares]
    leftover = settings.duration - sum(allocations)
    order = sorted(range(count), key=lambda index: shares[index] % 1, reverse=True)
    for index in order[:leftover]:
        allocations[index] += 1
    for section, minutes in zip(plan.sections, allocations, strict=True):
        section.minutes = minutes


class InterviewPlanner:
    def __init__(self, model: StructuredGenerator):
        self.model = model

    async def create(
        self, persona: CandidateProfile, job_description: str, settings: InterviewSettings
    ) -> InterviewPlan:
        # Resolve competencies, then generate a mixed interview with validated coverage.
        competencies = explicit_competencies(job_description)
        if competencies is None:
            requirements = await self.model.generate(
                ROLE_REQUIREMENTS,
                {"job_description": job_description},
                RoleRequirements,
            )
            competencies = list(dict.fromkeys(requirements.competencies))
        schema = planning_schema(competencies, settings, bool(persona.projects))

        def prepare_plan(value: BaseModel) -> InterviewPlan:
            # Check domain rules inside generation so invalid output can use the repair attempt.
            plan = as_interview(value, competencies)
            allocate_time(plan, settings)
            validate_plan(plan, persona, settings)
            return plan

        def check_plan(value: BaseModel) -> None:
            prepare_plan(value)

        generated = await self.model.generate(
            PLANNER,
            {
                "candidate": persona.model_dump(),
                "job_description": job_description,
                "settings": settings.model_dump(),
                "required_competencies": competencies,
                "interview_flow": {
                    f"section_{index}": kind
                    for index, kind in enumerate(
                        interview_flow(settings, bool(persona.projects)), 1
                    )
                },
            },
            schema,
            check_plan,
        )
        return prepare_plan(generated)
