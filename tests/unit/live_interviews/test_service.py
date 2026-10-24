import asyncio

import pytest

from backend.common.errors import Conflict, NotFound, Unavailable
from backend.features.live_interviews.audio_service import AudioInterviewService
from backend.features.live_interviews.models import AnswerInput
from backend.features.live_interviews.service import LiveInterviewService
from backend.features.live_interviews.sessions import SessionRegistry
from tests.factories import preparation, wav_bytes
from tests.fakes import BlockingReasoner, FakePreparation, FakeReasoner, FakeSpeech


async def engine(reasoner=None):
    now = [1000.0]
    live = LiveInterviewService(
        SessionRegistry(), FakePreparation(preparation()), reasoner, clock=lambda: now[0], timeout=1
    )
    state = await live.create("a" * 32)
    return live, state, now


def answer(state):
    return AnswerInput(
        prompt_id=state.current_prompt.id, answer="Use transactions and a unique constraint."
    )


async def test_progression_fallback_and_stale_prompt():
    live, state, now = await engine(FakeReasoner("clarify"))
    original = answer(state)
    for _ in range(3):
        result = await live.answer(state.session_id, answer(state))
        state = result.session
    assert state.question_number == 2
    assert result.transition.reason == "follow_up_limit_reached"
    with pytest.raises(Conflict, match="no longer current"):
        await live.answer(state.session_id, original)
    assert "scoring_guidance" not in state.model_dump_json()
    now[0] += 45 * 60
    assert live.get(state.session_id).status == "completed"


async def test_busy_guard_and_cancellation_leave_question_retryable():
    reasoner = BlockingReasoner()
    live, state, _ = await engine(reasoner)
    body = answer(state)
    pending = asyncio.create_task(live.answer(state.session_id, body))
    await reasoner.started.wait()
    for operation in [lambda: live.get(state.session_id), lambda: live.end(state.session_id)]:
        with pytest.raises(Conflict, match="busy"):
            operation()
    with pytest.raises(Conflict, match="busy"):
        await live.answer(state.session_id, body)
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending
    assert live.get(state.session_id) == state
    reasoner.release.set()
    assert (await live.answer(state.session_id, body)).session.question_number == 2


async def test_timeout_falls_back_and_restart_has_no_sessions():
    live, state, _ = await engine(BlockingReasoner())
    live._timeout = 0.01
    result = await live.answer(state.session_id, answer(state))
    assert not result.transition.assessment_available
    assert result.transition.reason == "assessment_fallback"
    fresh, _, _ = await engine(FakeReasoner())
    with pytest.raises(NotFound):
        fresh.get(state.session_id)
    disabled, state, _ = await engine()
    with pytest.raises(Unavailable):
        await disabled.answer(state.session_id, answer(state))


async def test_deadline_is_enforced_after_model_call():
    reasoner = BlockingReasoner()
    live, state, now = await engine(reasoner)
    pending = asyncio.create_task(live.answer(state.session_id, answer(state)))
    await reasoner.started.wait()
    now[0] = state.deadline_at
    reasoner.release.set()
    result = await pending
    assert result.session.status == "completed"
    assert result.transition.reason == "deadline_expired"


async def test_audio_uses_same_guard_and_text_answer_flow():
    live, state, _ = await engine(FakeReasoner())
    speech = FakeSpeech()
    audio = AudioInterviewService(live, speech, speech)
    assert await audio.prompt_audio(state.session_id, state.current_prompt.id) == wav_bytes()
    result = await audio.answer(state.session_id, wav_bytes(), state.current_prompt.id)
    assert result.transcription.text and result.session.question_number == 2
    with pytest.raises(Conflict):
        await audio.answer(state.session_id, wav_bytes(), state.current_prompt.id)


async def test_audio_cancellation_releases_busy_guard():
    class PendingSpeech(FakeSpeech):
        started = asyncio.Event()

        async def transcribe(self, content):
            self.started.set()
            await asyncio.Event().wait()

    live, state, _ = await engine(FakeReasoner())
    speech = PendingSpeech()
    audio = AudioInterviewService(live, speech, speech)
    pending = asyncio.create_task(
        audio.answer(state.session_id, wav_bytes(), state.current_prompt.id)
    )
    await speech.started.wait()
    with pytest.raises(Conflict):
        await audio.prompt_audio(state.session_id, state.current_prompt.id)
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending
    assert live.get(state.session_id) == state


async def test_synthesis_cannot_outlive_deadline():
    live, state, now = await engine(FakeReasoner())

    class SlowSpeech(FakeSpeech):
        async def synthesize(self, text):
            now[0] = state.deadline_at
            return wav_bytes()

    audio = AudioInterviewService(live, None, SlowSpeech())
    with pytest.raises(Conflict, match="no longer accepting"):
        await audio.prompt_audio(state.session_id, state.current_prompt.id)
    assert live.get(state.session_id).status == "completed"


async def test_speech_failure_does_not_change_session():
    class FailedSpeech(FakeSpeech):
        async def transcribe(self, content):
            raise Unavailable("Speech unavailable")

    live, state, _ = await engine(FakeReasoner())
    audio = AudioInterviewService(live, FailedSpeech(), None)
    with pytest.raises(Unavailable):
        await audio.answer(state.session_id, wav_bytes(), state.current_prompt.id)
    assert live.get(state.session_id) == state


async def test_invalid_assessment_uses_fallback_without_evidence():
    class InvalidReasoner:
        async def assess(self, *args):
            return {"action": "invented"}

    live, state, _ = await engine(InvalidReasoner())
    result = await live.answer(state.session_id, answer(state))
    assert not result.transition.assessment_available
    with live.operation(state.session_id) as internal:
        assert internal.evidence == []
