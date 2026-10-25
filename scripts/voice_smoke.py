"""Real local WebRTC/model smoke test using synthetic speech, never the user's mic.

Run with the voice environment after starting API, LiveKit, and agent:
python scripts/voice_smoke.py [--soak-seconds 900]
"""

import argparse
import asyncio
import json
import statistics
import sys
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx
import numpy as np
from livekit import rtc

from backend.integrations.voice.speech import GeminiSpeech, pcm16
from backend.modules.pre_interview.preparation.storage import MarkdownPreparationStore
from backend.settings import Settings
from tests.factories import preparation, resume_pdf


async def main(soak: int, reconnect: bool = False, turns: int = 1) -> None:
    settings = Settings.model_validate({})
    sample = preparation(candidate_id=uuid4().hex)
    if turns > 1:
        originals = sample.plan.sections
        sample.plan.sections = [originals[i % len(originals)].model_copy(deep=True)
                                for i in range(turns + 2)]
        sample.settings.duration = 60
        for i, section in enumerate(sample.plan.sections):
            section.minutes = 60 // len(sample.plan.sections) + (i < 60 % len(sample.plan.sections))
            section.questions[0].question = f"For scenario {i + 1}, " + section.questions[0].question[0].lower() + section.questions[0].question[1:]
    store = MarkdownPreparationStore(settings.data_dir / "demo/candidates")
    try:
        await store.load(sample.candidate_id)
    except Exception:
        await store.create(sample, resume_pdf())
    speech = GeminiSpeech(settings)
    try:
        audio = b"".join([chunk async for chunk in speech.audio(
            "I would use a database transaction and a unique constraint to prevent duplicate bookings."
        )])
        samples = np.frombuffer(audio, dtype="<i2").astype(np.float32) / 32768
        rate = 24000
    finally:
        await speech.close()
    room = rtc.Room()
    events: list[dict[str, Any]] = []
    audio_frames = 0
    audio_activity: list[float] = []
    audio_present = asyncio.Event()
    caption_seen = asyncio.Event()
    speaking = asyncio.Event()
    listening = asyncio.Event()
    readers: list[asyncio.Task[Any]] = []

    @room.on("data_received")
    def data(packet: rtc.DataPacket) -> None:
        event = json.loads(packet.data)
        events.append({**event, "received_at": time.monotonic()})
        if event.get("kind") == "state":
            if event.get("state") == "speaking":
                speaking.set()
                listening.clear()
            if event.get("state") == "listening":
                listening.set()
        if event.get("kind") == "caption" and event.get("text"):
            caption_seen.set()

    @room.on("track_subscribed")
    def subscribed(track: rtc.Track, publication: Any, participant: Any) -> None:
        async def consume() -> None:
            nonlocal audio_frames
            stream = rtc.AudioStream(track)
            try:
                async for item in stream:
                    audio_frames += 1
                    pcm = np.frombuffer(item.frame.data, dtype="<i2").astype(np.float32)
                    if pcm.size and float(np.sqrt(np.mean(pcm * pcm))) > 150:
                        audio_activity.append(time.monotonic())
                        audio_present.set()
            finally:
                await stream.aclose()

        readers.append(asyncio.create_task(consume()))

    async with httpx.AsyncClient(
        base_url=settings.backend_url, timeout=15, trust_env=False
    ) as client:
        response = await client.post(
            "/api/live-sessions", json={"candidate_id": sample.candidate_id}
        )
        response.raise_for_status()
        state = response.json()
        base = "/api/live-sessions/" + state["session_id"]
        try:
            response = await client.post(base + "/voice")
            response.raise_for_status()
            connection = response.json()
            await room.connect(connection["url"], connection["token"])
            source = rtc.AudioSource(rate, 1, queue_size_ms=100)
            track = rtc.LocalAudioTrack.create_audio_track("synthetic-answer", source)
            await room.local_participant.publish_track(
                track, rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE)
            )
            await asyncio.wait_for(speaking.wait(), 90)
            await asyncio.wait_for(listening.wait(), 90)
            assert audio_frames > 0, "No interviewer audio received"
            initial_frames = audio_frames
            if reconnect:
                await room.disconnect()
                await source.aclose()
                await asyncio.sleep(1)
                room = rtc.Room()
                room.on("data_received", data)
                room.on("track_subscribed", subscribed)
                source = rtc.AudioSource(rate, 1, queue_size_ms=100)
                response = await client.post(base + "/voice")
                response.raise_for_status()
                connection = response.json()
                speaking.clear()
                listening.clear()
                await room.connect(connection["url"], connection["token"])
                track = rtc.LocalAudioTrack.create_audio_track("synthetic-answer-rejoined", source)
                await room.local_participant.publish_track(
                    track, rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE)
                )
                await asyncio.wait_for(speaking.wait(), 15)
                await asyncio.wait_for(listening.wait(), 15)
                resumed = (await client.get(base)).json()
                assert resumed["current_prompt"]["id"] == state["current_prompt"]["id"]
            started = time.monotonic()
            reports = []
            for turn in range(turns):
                # Exercise real speech, assessment, streaming playback and interruption.
                old_prompt = state["current_prompt"]["id"]
                caption_seen.clear()
                agent = next(iter(room.remote_participants.values()))
                speaking.clear()
                audio_present.clear()
                await room.local_participant.perform_rpc(
                    destination_identity=agent.identity, method="control", payload='{"action":"repeat"}'
                )
                await asyncio.wait_for(speaking.wait(), 10)
                await asyncio.wait_for(audio_present.wait(), 20)
                await asyncio.sleep(0.2)
                speech_started = time.monotonic()
                speaking.clear()
                for offset in range(0, len(samples), rate // 50):
                    chunk = samples[offset : offset + rate // 50]
                    await source.capture_frame(rtc.AudioFrame(pcm16(chunk), rate, 1, len(chunk)))
                await source.wait_for_playout()
                speech_ended = time.monotonic()
                audio_present.clear()
                for _ in range(100):
                    await source.capture_frame(
                        rtc.AudioFrame(b"\0\0" * (rate // 50), rate, 1, rate // 50)
                    )
                await asyncio.wait_for(caption_seen.wait(), 20)
                deadline = time.monotonic() + 30
                while time.monotonic() < deadline:
                    state = (await client.get(base)).json()
                    if (state.get("current_prompt") or {}).get("id") != old_prompt:
                        break
                    await asyncio.sleep(0.5)
                history = (await client.get(base + "/history")).json()
                candidate = [e for e in history["events"] if e["kind"] == "candidate"]
                assert candidate, "No finalized answer reached backend"
                assert "transaction" in candidate[-1]["text"].lower(), candidate[-1]
                await asyncio.wait_for(speaking.wait(), 15)
                await asyncio.wait_for(audio_present.wait(), 20)
                reply_times = [
                    e["received_at"]
                    for e in events
                    if e.get("kind") == "state"
                    and e.get("state") == "speaking"
                    and e["received_at"] > speech_ended
                ]
                stopped_times = [
                    e["received_at"]
                    for e in events
                    if e.get("kind") == "state"
                    and e.get("state") == "listening"
                    and speech_started < e["received_at"] < speech_ended
                ]
                audible_replies = [t for t in audio_activity if t > speech_ended]
                interruption_tail = [speech_started] + [
                    t for t in audio_activity if speech_started <= t < speech_ended
                ] + [speech_ended]
                stopped = next((a for a, b in zip(interruption_tail, interruption_tail[1:])
                                if b - a >= 0.2), None)
                report = {
                    "passed": True,
                    "session_id": state["session_id"],
                    "audio_frames": audio_frames,
                    "initial_audio_frames": initial_frames,
                    "caption_events": sum(e.get("kind") == "caption" for e in events),
                    "recognized_answer": candidate[-1]["text"],
                    "question_number": state["question_number"],
                    "progression": state["progression"],
                    "soak_seconds": soak,
                    "microphone_used": False,
                    "reconnect_tested": reconnect,
                    "response_delay_seconds": round(min(audible_replies) - speech_ended, 3)
                    if audible_replies
                    else None,
                    "interruption_stop_seconds": round(stopped - speech_started, 3)
                    if stopped is not None
                    else None,
                }
                report["state_response_delay_seconds"] = round(min(reply_times) - speech_ended, 3) if reply_times else None
                report["state_interruption_stop_seconds"] = round(min(stopped_times) - speech_started, 3) if stopped_times else None
                report["latency_targets_met"] = bool(
                    report["response_delay_seconds"] is not None
                    and report["response_delay_seconds"] < 3
                    and report["interruption_stop_seconds"] is not None
                    and report["interruption_stop_seconds"] < 0.7
                )
                reports.append(report)
                Path("work/voice-smoke-report.json").write_text(json.dumps(report, indent=2))
                print(json.dumps(report), flush=True)
                await asyncio.wait_for(listening.wait(), 30)
            # Optional soak repeats the same prompt without advancing the interview.
            while time.monotonic() - started < soak:
                agent = next(
                    p
                    for p in room.remote_participants.values()
                    if p.kind == rtc.ParticipantKind.PARTICIPANT_KIND_AGENT
                )
                await room.local_participant.perform_rpc(
                    destination_identity=agent.identity,
                    method="control",
                    payload=json.dumps({"action": "repeat"}),
                )
                await asyncio.sleep(min(20, max(0, soak - (time.monotonic() - started))))
                status = (await client.get(base)).json()
                assert status["status"] == "active"
            delays = [r["response_delay_seconds"] for r in reports if r["response_delay_seconds"] is not None]
            stops = [r["interruption_stop_seconds"] for r in reports if r["interruption_stop_seconds"] is not None]
            summary = {
                "turns": reports, "soak_seconds": soak,
                "median_response_seconds": statistics.median(delays) if delays else None,
                "p95_response_seconds": float(np.percentile(delays, 95)) if delays else None,
                "median_interruption_seconds": statistics.median(stops) if stops else None,
                "fallback_count": sum(not p["assessment_available"] for p in state["progression"]),
            }
            Path("work/voice-benchmark-report.json").write_text(json.dumps(summary, indent=2))
            print(json.dumps({k:v for k,v in summary.items() if k != "turns"}), flush=True)
        finally:
            await client.post(base + "/end")
            await room.disconnect()
            for reader in readers:
                reader.cancel()
            await asyncio.gather(*readers, return_exceptions=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--soak-seconds", type=int, default=0)
    parser.add_argument("--reconnect", action="store_true")
    parser.add_argument("--turns", type=int, default=1)
    args = parser.parse_args()
    asyncio.run(main(args.soak_seconds, args.reconnect, args.turns))
