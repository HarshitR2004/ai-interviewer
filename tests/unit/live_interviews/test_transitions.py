import pytest

from backend.modules.live_interviews.models import Decision
from backend.modules.live_interviews.transitions import fallback, new_session, transition
from tests.factories import preparation


def test_transitions_are_deterministic_and_explain_overrides():
    value = preparation()
    first = new_session("session", value, 1000, "first")
    second = new_session("session", value, 1000, "first")
    first.deadline_at = second.deadline_at = 4000
    first.follow_up_count = second.follow_up_count = 2
    decision = Decision(action="follow_up", next_question="Explain the tradeoff.")
    a = transition(first, decision, 1001, "next", True)
    b = transition(second, decision, 1001, "next", True)
    assert first == second and a == b
    assert a.proposed_action == "follow_up" and a.executed_action == "advance"
    assert a.reason == "follow_up_limit_reached"


def test_deadline_overrides_model_and_closes_session():
    state = new_session("session", preparation(), 1000, "first")
    outcome = transition(state, Decision(action="advance"), state.deadline_at, "next", True)
    assert outcome.reason == "deadline_expired"
    assert state.status == "completed" and state.current_prompt is None


@pytest.mark.parametrize("kind,index", [("introduction", 0), ("closing", 1)])
def test_context_turns_are_not_scored_or_subjected_to_probes(kind, index):
    state = new_session("session", preparation(), 1000, "first")
    state.deadline_at = 4000
    state.question_index = index
    state.section.kind = kind
    state.question.scoring_guidance = None
    state.question.strong_answer_signals = []
    state.question.follow_ups = []
    outcome = transition(
        state,
        Decision(
            action="follow_up", next_question="Tell me more.", evidence=["Should not be assessed"]
        ),
        1001,
        "next",
        True,
    )
    assert state.evidence == []
    assert state.follow_up_count == 0
    assert outcome.executed_action == ("finish" if kind == "closing" else "advance")


def test_assessment_failure_does_not_blindly_ask_prepared_probes():
    state = new_session("session", preparation(), 1000, "first")
    assert state.question.follow_ups
    assert fallback(state).action == "advance"
