from backend.shared.markdown import bullets

from .models import InterviewPlan


def render_interview(plan: InterviewPlan) -> str:
    parts = [
        f"# Interview: {plan.role}",
        "## Required competencies\n" + bullets(plan.required_competencies),
    ]
    for section in plan.sections:
        parts.append(
            f"## {section.title} — {section.minutes} minutes\n\nCompetency: {section.competency}"
        )
        for question in section.questions:
            scoring = question.scoring_guidance
            parts.append(
                f"### {question.question}\n\nContext: {question.candidate_context or 'General technical discussion.'}\n\nProject: {question.project_id or 'Not project-specific'}\n\nFollow-ups:\n{bullets(question.follow_ups)}\n\nStrong-answer signals:\n{bullets(question.strong_answer_signals)}\n\nScoring:\n- 1: {scoring.weak}\n- 3: {scoring.adequate}\n- 5: {scoring.strong}"
            )
    parts.append(f"Total: {sum(section.minutes for section in plan.sections)} minutes.")
    return "\n\n".join(parts) + "\n"
