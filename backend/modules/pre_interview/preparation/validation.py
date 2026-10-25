from backend.modules.pre_interview.profiles.models import CandidateProfile

from .blueprint import interview_flow
from .models import InterviewPlan, InterviewSettings


def validate_plan(
    plan: InterviewPlan, persona: CandidateProfile, settings: InterviewSettings
) -> None:
    # Enforce duration, competency coverage, valid project references, and distinct questions.
    if sum(section.minutes for section in plan.sections) != settings.duration:
        raise ValueError("Section minutes must total the requested duration.")
    covered = {
        name.casefold()
        for section in plan.sections
        if section.scored
        for name in [section.competency, *section.covered_competencies]
    }
    missing = [c for c in plan.required_competencies if c.casefold() not in covered]
    if missing:
        raise ValueError(
            f"Uncovered role competencies: {missing}. Include them in an appropriate assessed section's competency or covered_competencies."
        )
    projects = {p.id for p in persona.projects}
    questions = set()
    if plan.format_version == 2:
        kinds = [section.kind for section in plan.sections]
        if kinds != interview_flow(settings, bool(projects)):
            raise ValueError(
                "Use the required conversational mix, beginning with introduction and ending with closing."
            )
        anchors = {
            section.questions[0].project_id
            for section in plan.sections
            if section.kind in {"project_overview", "project_detail"}
        }
        if projects and (None in anchors or len(anchors) != 1):
            raise ValueError(
                "The project overview and detail must discuss the same supplied project."
            )
    for section in plan.sections:
        if plan.format_version == 2:
            if section.scored:
                if section.competency not in plan.required_competencies:
                    raise ValueError("The primary competency must come from the role requirements.")
                if section.competency not in section.covered_competencies:
                    raise ValueError("Include the primary competency in covered_competencies.")
                if any(c not in plan.required_competencies for c in section.covered_competencies):
                    raise ValueError("Covered competencies must come from the role requirements.")
            elif section.covered_competencies:
                raise ValueError("Introduction and closing must not assess competencies.")
        for question in section.questions:
            if section.scored and (
                question.scoring_guidance is None or not question.strong_answer_signals
            ):
                raise ValueError(
                    "Assessed questions require scoring anchors and observable answer signals."
                )
            if not section.scored and (
                question.scoring_guidance is not None
                or question.strong_answer_signals
                or question.follow_ups
            ):
                raise ValueError(
                    "Introduction and closing must not be scored or have prepared probes."
                )
            if question.project_id is not None and question.project_id not in projects:
                raise ValueError(
                    f"Unknown project_id {question.project_id}. Use null or one of {sorted(projects)}."
                )
            normalized = " ".join(question.question.casefold().split())
            if normalized in questions:
                raise ValueError("Questions must not repeat.")
            questions.add(normalized)
            if plan.format_version == 2:
                if len(question.follow_ups) > 2:
                    raise ValueError("Prepare at most two optional probes for a question.")
                if len(question.question.split()) > 55 or question.question.count("?") > 1:
                    raise ValueError(
                        "Use one short spoken lead question, at most 55 words and one question mark."
                    )
                if any(
                    len(text.split()) > 30 or text.count("?") > 1 for text in question.follow_ups
                ):
                    raise ValueError(
                        "Each optional probe must be one short question of at most 30 words."
                    )
                if section.kind == "project_detail" and question.project_id is None:
                    raise ValueError("A project detail question must reference a supplied project.")
                if (
                    section.kind not in {"project_overview", "project_detail"}
                    and question.project_id is not None
                ):
                    raise ValueError(
                        "General questions must not assert project-specific experience."
                    )
