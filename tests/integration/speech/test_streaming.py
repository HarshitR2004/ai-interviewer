import asyncio
from types import SimpleNamespace

import pytest
from livekit.agents import APIConnectOptions, APIError, stt
from livekit.agents.types import DEFAULT_API_CONNECT_OPTIONS

from backend.integrations.voice.speech import GeminiStream, GeminiSTT, GeminiTTS


class Speech:
    def __init__(self, fail_after=False):
        self.calls = 0
        self.closed = False
        self.fail_after = fail_after

    async def audio(self, text):
        self.calls += 1
        try:
            yield b"\0\0" * 2400
            if self.fail_after:
                raise RuntimeError("provider failure")
            await asyncio.Event().wait()
        finally:
            self.closed = True


async def test_tts_streams_and_cancels():
    speech = Speech()
    stream = GeminiTTS(speech).synthesize("Question")
    event = await asyncio.wait_for(anext(stream), 3)
    assert event.frame.sample_rate == 24000
    assert not speech.closed
    await stream.aclose()
    assert speech.closed


async def test_tts_does_not_retry_after_audio():
    speech = Speech(fail_after=True)
    stream = GeminiTTS(speech).synthesize("Question", conn_options=APIConnectOptions(max_retry=0))
    with pytest.raises(APIError):
        async for _ in stream:
            pass
    assert speech.calls == 1


async def test_transcription_events_and_renewal():
    class Session:
        async def receive(self):
            for interim, final in [("I use", None), (None, "I use a transaction.")]:
                yield SimpleNamespace(server_content=SimpleNamespace(
                    interim_input_transcription=SimpleNamespace(text=interim) if interim else None,
                    input_transcription=SimpleNamespace(text=final) if final else None,
                ))
    stream = GeminiStream(GeminiSTT(SimpleNamespace()), DEFAULT_API_CONNECT_OPTIONS)
    stream._task.cancel()
    await asyncio.gather(stream._task, return_exceptions=True)
    events = []
    stream.emit = lambda kind, text="": events.append((kind, text))
    await stream.receive(Session(), -100000)
    assert [e[0] for e in events] == [stt.SpeechEventType.START_OF_SPEECH,
        stt.SpeechEventType.INTERIM_TRANSCRIPT, stt.SpeechEventType.FINAL_TRANSCRIPT,
        stt.SpeechEventType.END_OF_SPEECH]
    assert stream.renew.is_set()
    await stream.aclose()


async def test_tts_retries_once_before_first_audio():
    class RetrySpeech:
        calls = 0

        async def audio(self, text):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("temporary provider failure")
            yield b"\0\0" * 2400

    speech = RetrySpeech()
    stream = GeminiTTS(speech).synthesize("Question", conn_options=APIConnectOptions(max_retry=0))
    frames = [event async for event in stream]
    assert frames
    assert speech.calls == 2


async def test_tts_exhausts_retry_without_audio():
    class FailedSpeech:
        calls = 0

        async def audio(self, text):
            self.calls += 1
            raise RuntimeError("provider unavailable")
            yield b""  # pragma: no cover

    speech = FailedSpeech()
    stream = GeminiTTS(speech).synthesize("Question", conn_options=APIConnectOptions(max_retry=0))
    with pytest.raises(APIError):
        async for _ in stream:
            pass
    assert speech.calls == 2
