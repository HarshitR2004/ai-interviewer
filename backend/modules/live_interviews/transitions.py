"""Pure in-memory interview rules; time and prompt IDs are provided by the caller."""

from backend.common.errors import Conflict
from backend.modules.pre_interview.preparation.models import Preparation

from .models import Decision, Evidence, Prompt, SessionState, TransitionExplanation

MAX_FOLLOW_UPS = 2


def new_session(
    session_id: str, preparation: Preparation, now: float, prompt_id: str
) -> SessionState:
    # Copy preparation so later replanning cannot alter a running interview.
    return SessionState(
        session_id=session_id,
        preparation=preparation.model_copy(deep=True),
        section_started_at=now,
        deadline_at=0,
        current_prompt=Prompt(
            id=prompt_id,
            question_id="s1q1",
            text=preparation.plan.sections[0].questions[0].question,
        ),
    )


def close(state: SessionState) -> None:
    # Mark completion and remove the prompt that would otherwise accept answers.
    state.status = "completed"
    state.current_prompt = None
    state.revision += 1
    state.pending_turn = None


def expire(state: SessionState, now: float) -> None:
    if state.status == "active" and now >= state.deadline_at:
        close(state)
        state.completion_reason = "deadline_expired"
    elif state.disconnected_at is not None and now - state.disconnected_at >= 30:
        close(state)
        state.completion_reason = "disconnected"


def require_prompt(state: SessionState, prompt_id: str, now: float) -> None:
    expire(state, now)
    if state.status != "active":
        raise Conflict("Interview is no longer accepting answers.")
    if state.current_prompt is None or state.current_prompt.id != prompt_id:
        raise Conflict("This prompt is no longer current.")


def fallback(state: SessionState) -> Decision:
    # Without assessment, do not blindly probe an answer that may already be sufficient.
    return Decision(action="advance")


def transition(
    state: SessionState, decision: Decision, now: float, prompt_id: str, available: bool
) -> TransitionExplanation:
    # Apply time and follow-up limits to the proposed action, then record the outcome.
    action = decision.action
    reason = "model_approved" if available else "assessment_fallback"
    if not state.section.scored and decision.intent == "answer":
        action, reason = "advance", "context_complete"
    if now >= state.deadline_at:
        action, reason = "finish", "deadline_expired"
    elif (
        action in {"clarify", "follow_up"}
        and now >= state.section_started_at + state.section.minutes * 60
    ):
        action, reason = "advance", "section_expired"
    elif action in {"clarify", "follow_up"} and state.follow_up_count >= MAX_FOLLOW_UPS:
        action, reason = "advance", "follow_up_limit_reached"
    # Fallback questions keep the interview moving but must not create assessment evidence.
    if available and state.section.scored:
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
