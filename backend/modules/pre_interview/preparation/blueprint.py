"""Conversation structure and pacing, independent of the generated question wording."""

from .models import InterviewSettings, QuestionKind


def interview_flow(settings: InterviewSettings, has_projects: bool) -> list[QuestionKind]:
    overview: QuestionKind = "project_overview" if has_projects else "experience_overview"
    depth: QuestionKind = "project_detail" if has_projects else "role_scenario"
    flow: list[QuestionKind] = ["introduction", overview, "fundamentals", "framework", depth]
    if settings.duration > 20:
        # Without resume projects, depth is already a scenario; avoid two near-identical slots.
        flow.extend(["role_scenario" if has_projects else "fundamentals", "behavioral"])
    if settings.duration >= 60:
        flow.extend(["fundamentals", "role_scenario"])
    return [*flow, "closing"]
