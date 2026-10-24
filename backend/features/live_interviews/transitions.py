"""Pure in-memory interview rules; time and prompt IDs are provided by the caller."""

from backend.features.preparation.models import Preparation

from .models import Decision, Evidence, Prompt, SessionState, TransitionExplanation


def new_session(
    session_id: str, preparation: Preparation, now: float, prompt_id: str
) -> SessionState:
    return SessionState(
        session_id=session_id,
        preparation=preparation.model_copy(deep=True),
        section_started_at=now,
        deadline_at=now + preparation.settings.duration * 60,
        current_prompt=Prompt(
            id=prompt_id,
            question_id="s1q1",
            text=preparation.plan.sections[0].questions[0].question,
        ),
    )


def close(state: SessionState) -> None:
    state.status = "completed"
    state.current_prompt = None


def fallback(state: SessionState) -> Decision:
    for text in state.question.follow_ups:
        if text not in state.used_prepared_followups and state.follow_up_count < 2:
            return Decision(action="follow_up", next_question=text)
    return Decision(action="advance")


def transition(
    state: SessionState, decision: Decision, now: float, prompt_id: str, available: bool
) -> TransitionExplanation:
    action = decision.action
    reason = "model_approved" if available else "assessment_fallback"
    if now >= state.deadline_at:
        action, reason = "finish", "deadline_expired"
    elif (
        action in {"clarify", "follow_up"}
        and now >= state.section_started_at + state.section.minutes * 60
    ):
        action, reason = "advance", "section_expired"
    elif action in {"clarify", "follow_up"} and state.follow_up_count >= 2:
        action, reason = "advance", "follow_up_limit_reached"
    if available:
        state.evidence.append(
            Evidence(
                question_id=state.question_id,
                evidence=decision.evidence,
                missing_evidence=decision.missing_evidence,
            )
        )
    if action in {"clarify", "follow_up"}:
        assert decision.next_question is not None
        state.follow_up_count += 1
        state.current_prompt = Prompt(
            id=prompt_id, question_id=state.question_id, text=decision.next_question
        )
        if decision.next_question in state.question.follow_ups:
            state.used_prepared_followups.append(decision.next_question)
    elif action == "advance":
        if state.question_index + 1 == len(state.preparation.plan.sections):
            action, reason = "finish", "questions_exhausted"
        else:
            state.question_index += 1
            state.follow_up_count = 0
            state.used_prepared_followups = []
            state.section_started_at = now
            state.current_prompt = Prompt(
                id=prompt_id, question_id=state.question_id, text=state.question.question
            )
    if action == "finish":
        close(state)
    result = TransitionExplanation(
        proposed_action=decision.action,
        executed_action=action,
        reason=reason,
        assessment_available=available,
    )
    state.progression.append(result)
    return result
