from backend.features.live_interviews.models import Decision
from backend.features.live_interviews.transitions import new_session, transition
from tests.factories import preparation


def test_transitions_are_deterministic_and_explain_overrides():
    value = preparation()
    first = new_session("session", value, 1000, "first")
    second = new_session("session", value, 1000, "first")
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
