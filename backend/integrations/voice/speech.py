"""Gemini hosted speech adapters. No local inference or saved audio."""
from __future__ import annotations

import asyncio
import base64
import logging
import time
from contextlib import aclosing
from typing import Any
from uuid import uuid4

import numpy as np
from google import genai
from livekit import rtc
from livekit.agents import APIConnectOptions, APIError, stt, tts
from livekit.agents.language import LanguageCode
from livekit.agents.types import DEFAULT_API_CONNECT_OPTIONS, NOT_GIVEN

log = logging.getLogger(__name__)


def pcm16(samples: Any) -> bytes:
    return (np.clip(np.asarray(samples).reshape(-1), -1, 1) * 32767).astype("<i2").tobytes()


class GeminiSpeech:
    def __init__(self, settings: Any, client: Any = None):
        if not settings.llm_api_key:
            raise ValueError("Configure GEMINI_API_KEY for hosted speech.")
        self.client = client or genai.Client(api_key=settings.llm_api_key.get_secret_value())
        self.interactions = self.client.aio.interactions
        self.stt_model = settings.gemini_stt_model
        self.tts_model = settings.gemini_tts_model
        self.voice = settings.gemini_tts_voice

    async def close(self) -> None:
        await self.client.aio.aclose()

    async def audio(self, text: str) -> Any:
        # Omit mime_type: the preview rejects explicit audio/l16 but streams PCM by default.
        stream = await self.interactions.create(
            model=self.tts_model,
            input="Synthesize speech. Read only the following transcript, exactly as written:\n" + text,
            response_format={"type": "audio"},
            generation_config={"speech_config": [{"voice": self.voice}]},
            stream=True,
        )
        try:
            async for event in stream:
                if event.event_type == "step.delta" and event.delta.type == "audio":
                    if event.delta.mime_type not in {None, "audio/l16"}:
                        raise RuntimeError("Gemini returned an unsupported audio format.")
                    yield base64.b64decode(event.delta.data)
        finally:
            await stream.close()


class GeminiSTT(stt.STT[Any]):
    def __init__(self, speech: GeminiSpeech):
        super().__init__(capabilities=stt.STTCapabilities(
            streaming=True, interim_results=True, offline_recognize=False,
        ))
        self.speech = speech

    async def _recognize_impl(self, buffer: Any, *, language: Any = NOT_GIVEN,
                              conn_options: APIConnectOptions) -> stt.SpeechEvent:
        raise NotImplementedError("Use streaming transcription.")

    def stream(self, *, language: Any = NOT_GIVEN,
               conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS) -> GeminiStream:
        return GeminiStream(self, conn_options)


class GeminiStream(stt.RecognizeStream):
    def __init__(self, provider: GeminiSTT, options: APIConnectOptions):
        self.provider = provider
        self.speaking = False
        self.renew = asyncio.Event()
        super().__init__(stt=provider, conn_options=options, sample_rate=16000)

    def emit(self, kind: stt.SpeechEventType, text: str = "") -> None:
        self._event_ch.send_nowait(stt.SpeechEvent(
            type=kind,
            alternatives=[stt.SpeechData(language=LanguageCode("en"), text=text)] if text else [],
        ))

    async def receive(self, session: Any, started: float) -> None:
        while True:
            async for response in session.receive():
                activity = getattr(response, "voice_activity", None)
                if activity and "ACTIVITY_START" in str(activity.voice_activity_type) and not self.speaking:
                    self.speaking = True
                    self.emit(stt.SpeechEventType.START_OF_SPEECH)
                content = response.server_content
                if not content:
                    continue
                interim = getattr(content, "interim_input_transcription", None)
                final = getattr(content, "input_transcription", None)
                transcription = interim or final
                text = (transcription.text or "").strip() if transcription is not None else ""
                if text and not self.speaking:
                    self.speaking = True
                    self.emit(stt.SpeechEventType.START_OF_SPEECH)
                if interim and text:
                    self.emit(stt.SpeechEventType.INTERIM_TRANSCRIPT, text)
                if final and text:
                    self.emit(stt.SpeechEventType.FINAL_TRANSCRIPT, text)
                    self.emit(stt.SpeechEventType.END_OF_SPEECH)
                    self.speaking = False
                    if time.monotonic() - started >= 480:
                        self.renew.set()
                        return
            # receive() can end at a server turn boundary; keep the connection alive.
            await asyncio.sleep(0)

    async def renew_when_idle(self) -> None:
        await asyncio.sleep(480)
        while self.speaking:
            await asyncio.sleep(0.1)
        self.renew.set()

    async def _run(self) -> None:
        config: Any = {
            "response_modalities": ["TEXT"],
            "input_audio_transcription": {"language_codes": ["en-US"], "mode": "VERBATIM"},
            "realtime_input_config": {"automatic_activity_detection": {"silence_duration_ms": 700}},
        }
        try:
            while True:
                self.renew.clear()
                async with self.provider.speech.client.aio.live.connect(
                    model=self.provider.speech.stt_model, config=config,
                ) as session:
                    receiver = asyncio.create_task(self.receive(session, time.monotonic()))
                    rotation = asyncio.create_task(self.renew_when_idle())
                    next_frame = asyncio.create_task(self._input_ch.__anext__())
                    try:
                        while True:
                            done, _ = await asyncio.wait(
                                [receiver, rotation, next_frame], return_when=asyncio.FIRST_COMPLETED,
                            )
                            if rotation in done:
                                break
                            if receiver in done:
                                await receiver
                                if not self.renew.is_set():
                                    raise RuntimeError("Gemini transcription disconnected.")
                                break
                            try:
                                frame = next_frame.result()
                            except StopAsyncIteration:
                                return
                            if isinstance(frame, rtc.AudioFrame):
                                await session.send_realtime_input(audio={
                                    "data": bytes(frame.data), "mime_type": "audio/pcm;rate=16000",
                                })
                            next_frame = asyncio.create_task(self._input_ch.__anext__())
                    finally:
                        rotation.cancel()
                        receiver.cancel()
                        next_frame.cancel()
                        await asyncio.gather(receiver, rotation, next_frame, return_exceptions=True)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # No automatic replay/retry of unfinished candidate audio.
            raise APIError("Gemini transcription disconnected. Reconnect and repeat your answer.",
                           retryable=False) from exc


class GeminiTTS(tts.TTS[Any]):
    def __init__(self, speech: GeminiSpeech):
        super().__init__(capabilities=tts.TTSCapabilities(streaming=False),
                         sample_rate=24000, num_channels=1)
        self.speech = speech

    def synthesize(self, text: str, *,
                   conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS) -> GeminiAudio:
        return GeminiAudio(self, text, conn_options)


class GeminiAudio(tts.ChunkedStream):
    def __init__(self, provider: GeminiTTS, text: str, options: APIConnectOptions):
        self.provider = provider
        super().__init__(tts=provider, input_text=text, conn_options=options)

    async def _run(self, output_emitter: tts.AudioEmitter) -> None:
        output_emitter.initialize(request_id=uuid4().hex, sample_rate=24000,
                                  num_channels=1, mime_type="audio/pcm", frame_size_ms=20)
        emitted = False
        for attempt in range(2):
            try:
                async with aclosing(self.provider.speech.audio(self._input_text)) as audio:
                    async with asyncio.timeout(30):
                        async for chunk in audio:
                            if chunk:
                                output_emitter.push(chunk)
                                emitted = True
                if not emitted:
                    raise RuntimeError("Gemini returned no speech audio.")
                output_emitter.flush()
                return
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                if emitted or attempt:
                    raise APIError("Gemini speech failed. Use Repeat question.",
                                   retryable=False) from exc
