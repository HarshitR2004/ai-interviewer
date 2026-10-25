import asyncio
from uuid import uuid4

import pytest

from backend.common.errors import Conflict, InvalidInput, NotFound
from backend.modules.live_interviews.models import AgentEvent, Decision, TurnInput
from backend.modules.live_interviews.service import LiveInterviewService
from backend.modules.live_interviews.sessions import SessionRegistry
from backend.modules.live_interviews.storage import JsonHistoryStore
from tests.factories import preparation
from tests.fakes import BlockingReasoner, FakePreparation, FakeReasoner


async def engine(reasoner=None, *, timeout=1, history=None, start=True):
    now = [1000.0]
    live = LiveInterviewService(
        SessionRegistry(),
        FakePreparation(preparation()),
        reasoner or FakeReasoner(),
        clock=lambda: now[0],
        timeout=timeout,
        history=history,
    )
    state = await live.create("a" * 32)
    if start:
        live.event(state.session_id, AgentEvent(kind="ready"))
        state = live.event(state.session_id, AgentEvent(kind="joined"))
    return live, state, now


def body(state, text="Use a unique constraint and a transaction."):
    return TurnInput(prompt_id=state.current_prompt.id, turn_id=uuid4().hex, text=text)


async def test_waiting_does_not_consume_timer_and_one_interview():
    live, state, now = await engine(start=False)
    assert state.status == "waiting" and state.deadline_at == 0
    now[0] += 100
    with pytest.raises(Conflict):
        live.event(state.session_id, AgentEvent(kind="joined"))
    live.event(state.session_id, AgentEvent(kind="ready"))
    started = live.event(state.session_id, AgentEvent(kind="joined"))
    assert started.deadline_at == now[0] + 45 * 60
    with pytest.raises(Conflict):
        await live.create("a" * 32)


async def test_idempotent_turn_and_stale_prompt():
    reasoner = FakeReasoner()
    live, state, _ = await engine(reasoner)
    turn = body(state)
    result = await live.answer_from_transcript(state.session_id, turn)
    assert result.session.question_number == 2
    assert await live.answer_from_transcript(state.session_id, turn) == result
    assert reasoner.calls == 1
    with pytest.raises(Conflict, match="no longer current"):
        await live.answer_from_transcript(state.session_id, body(state))


async def test_end_is_responsive_during_assessment():
    reasoner = BlockingReasoner()
    live, state, _ = await engine(reasoner)
    task = asyncio.create_task(live.answer_from_transcript(state.session_id, body(state)))
    await reasoner.started.wait()
    assert live.get(state.session_id).status == "active"
    assert live.end(state.session_id).status == "completed"
    with pytest.raises(asyncio.CancelledError):
        await task
    assert live.history(state.session_id)["events"] == []


async def test_continuation_invalidates_generation_without_advancing():
    reasoner = BlockingReasoner()
    live, state, _ = await engine(reasoner)
    task = asyncio.create_task(live.answer_from_transcript(state.session_id, body(state)))
    await reasoner.started.wait()
    live.event(state.session_id, AgentEvent(kind="invalidate"))
    with pytest.raises(asyncio.CancelledError):
        await task
    assert live.get(state.session_id).current_prompt == state.current_prompt
    reasoner.release.set()
    result = await live.answer_from_transcript(
        state.session_id, body(state, "First part and continuation.")
    )
    assert result.session.question_number == 2
    assert len(live.history(state.session_id)["events"]) == 1


@pytest.mark.parametrize("intent", ["repeat", "clarification"])
async def test_commands_do_not_assess_or_advance(intent):
    class CommandReasoner:
        async def assess(self, *args):
            return Decision(
                intent=intent,
                action="advance",
                next_question="Explain how you handle simultaneous bookings.",
            )

    live, state, _ = await engine(CommandReasoner())
    result = await live.answer_from_transcript(state.session_id, body(state, "Could you repeat?"))
    assert result.session.current_prompt == state.current_prompt
    assert result.session.follow_up_count == 0 and result.transition is None
    assert live.history(state.session_id)["evidence"] == []


async def test_timeout_fallback_no_evidence():
    live, state, _ = await engine(BlockingReasoner(), timeout=0.01)
    result = await live.answer_from_transcript(state.session_id, body(state))
    assert result.transition.assessment_available is False
    assert result.transition.reason == "assessment_fallback"
    assert live.history(state.session_id)["evidence"] == []


async def test_disconnect_rejoin_and_expiry():
    live, state, now = await engine()
    live.event(state.session_id, AgentEvent(kind="disconnected"))
    now[0] += 20
    assert live.event(state.session_id, AgentEvent(kind="joined")).status == "active"
    live.event(state.session_id, AgentEvent(kind="disconnected"))
    now[0] += 31
    assert live.get(state.session_id).completion_reason == "disconnected"


async def test_history_survives_restart_and_no_audio(tmp_path):
    store = JsonHistoryStore(tmp_path)
    live, state, _ = await engine(history=store)
    live.event(
        state.session_id,
        AgentEvent(kind="playback", text=state.current_prompt.text, interrupted=True),
    )
    await live.answer_from_transcript(state.session_id, body(state))
    live.end(state.session_id)
    fresh, _, _ = await engine(history=store)
    with pytest.raises(NotFound):
        fresh.get(state.session_id)
    history = fresh.history(state.session_id)
    assert history["session"]["status"] == "completed"
    assert history["events"][0]["interrupted"] is True
    assert all(path.suffix == ".json" for path in tmp_path.iterdir())


async def test_blank_turn_is_not_saved():
    live, state, _ = await engine()
    with pytest.raises(InvalidInput):
        await live.answer_from_transcript(state.session_id, body(state, "   "))
    assert live.history(state.session_id)["events"] == []


async def test_deadline_cancels_pending_turn():
    reasoner = BlockingReasoner()
    live, state, now = await engine(reasoner)
    task = asyncio.create_task(live.answer_from_transcript(state.session_id, body(state)))
    await reasoner.started.wait()
    now[0] = state.deadline_at
    assert live.get(state.session_id).completion_reason == "deadline_expired"
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_agent_restart_fails_session_and_releases_single_slot():
    live, state, now = await engine()
    now[0] += 16
    assert live.get(state.session_id).completion_reason == "voice_agent_disconnected"
    assert (await live.create("a" * 32)).status == "waiting"


async def test_waiting_agent_timeout_releases_slot():
    live, state, now = await engine(start=False)
    now[0] += 181
    assert live.get(state.session_id).completion_reason == "voice_agent_not_ready"
    assert (await live.create("a" * 32)).status == "waiting"


async def test_last_turn_id_is_available_after_lost_response():
    live, state, _ = await engine()
    turn = body(state)
    await live.answer_from_transcript(state.session_id, turn)
    assert live.get(state.session_id).last_turn_id == turn.turn_id


async def test_spoken_repeat_still_works_when_model_is_unavailable():
    class FailedReasoner:
        async def assess(self, *args):
            raise RuntimeError("offline")

    live, state, _ = await engine(FailedReasoner())
    result = await live.answer_from_transcript(
        state.session_id, body(state, "Please repeat the question.")
    )
    assert result.session.current_prompt == state.current_prompt
    assert result.transition is None


async def test_clarification_failure_repeats_without_scoring():
    class FailedReasoner:
        async def assess(self, *args):
            raise RuntimeError("offline")

    live, state, _ = await engine(FailedReasoner())
    result = await live.answer_from_transcript(state.session_id, body(state, "What do you mean?"))
    assert result.session.current_prompt == state.current_prompt
    assert result.transition is None
    assert live.history(state.session_id)["evidence"] == []


async def test_history_marks_interrupted_backend_after_restart(tmp_path):
    store = JsonHistoryStore(tmp_path)
    live, state, _ = await engine(history=store)
    fresh, _, _ = await engine(history=store)
    assert fresh.history(state.session_id)["session"]["completion_reason"] == "backend_restarted"


async def test_only_one_model_call_per_pending_turn():
    reasoner = BlockingReasoner()
    live, state, _ = await engine(reasoner)
    first = asyncio.create_task(live.answer_from_transcript(state.session_id, body(state)))
    await reasoner.started.wait()
    with pytest.raises(Conflict, match="already being assessed"):
        await live.answer_from_transcript(state.session_id, body(state))
    reasoner.release.set()
    await first
    assert reasoner.calls == 1
