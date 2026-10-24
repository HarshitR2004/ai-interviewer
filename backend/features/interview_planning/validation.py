from backend.features.profiles.models import CandidateProfile

from .models import InterviewPlan, InterviewSettings


def validate_plan(
    plan: InterviewPlan, persona: CandidateProfile, settings: InterviewSettings
) -> None:
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
