from backend.features.profiles.models import Persona

from .models import InterviewPlan, InterviewSettings


def validate_plan(plan: InterviewPlan, persona: Persona, settings: InterviewSettings) -> None:
    if sum(section.minutes for section in plan.sections) != settings.duration:
        raise ValueError("Section minutes must total the requested duration.")
    covered = {section.competency.casefold() for section in plan.sections}
    missing = [c for c in plan.required_competencies if c.casefold() not in covered]
    if missing:
        raise ValueError(
            f"Sections are missing these exact competency names: {missing}. Use each name verbatim in section.competency. Current names: {[s.competency for s in plan.sections]}."
        )
    projects = {p.id for p in persona.projects}
    questions = set()
    for section in plan.sections:
        for question in section.questions:
            if question.project_id is not None and question.project_id not in projects:
                raise ValueError(
                    f"Unknown project_id {question.project_id}. Use null or one of {sorted(projects)}."
                )
            normalized = " ".join(question.question.casefold().split())
            if normalized in questions:
                raise ValueError("Questions must not repeat.")
            questions.add(normalized)


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
