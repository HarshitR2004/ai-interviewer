import io
import wave

from fastapi.testclient import TestClient

from backend.features.live_interviews.models import Decision
from backend.features.live_interviews.service import LiveInterviewService
from backend.features.live_interviews.storage import SQLiteRepository
from backend.main import create_app
from backend.shared.config import Settings


def wav_bytes():
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(16000)
        writer.writeframes(b"\x00\x00" * 1600)
    return buffer.getvalue()


class Source:
    def __init__(self, plan):
        self.plan = plan

    async def load(self, candidate_id):
        return {"plan": self.plan.model_dump(), "settings": {"duration": 45}}


class Reasoner:
    async def assess(self, snapshot, answer):
        return Decision(action="advance")


class FakeSpeech:
    def __init__(self):
        self.calls = 0

    async def transcribe(self, content):
        self.calls += 1
        return {"text": "Use a unique database constraint and a transaction."}

    async def synthesize(self, text):
        return wav_bytes()


def test_audio_answers_deduplicate_original_bytes(tmp_path, plan):
    service = LiveInterviewService(
        SQLiteRepository(tmp_path / "live.sqlite3"), Source(plan), Reasoner()
    )
    with TestClient(
        create_app(
            Settings(
                _env_file=None,
                data_dir=tmp_path,
                llm_base_url="https://llm.example/v1",
                llm_model="test-model",
            ),
            live_service=service,
        )
    ) as client:
        fake = FakeSpeech()
        client.app.state.speech_client = fake
        state = client.post(
            "/api/live-sessions", json={"candidate_id": "a" * 32, "event_id": "start"}
        ).json()
        base = f"/api/live-sessions/{state['session_id']}"
        prompt_id = state["current_prompt"]["id"]
        assert (
            client.get(base + "/prompt/audio", params={"prompt_id": prompt_id}).content
            == wav_bytes()
        )
        fields = {"event_id": "audio-1", "prompt_id": prompt_id}
        first = client.post(
            base + "/audio-answers", data=fields, files={"audio": ("a.wav", wav_bytes())}
        )
        assert first.status_code == 200
        assert first.json()["session"]["question_number"] == 2
        replay = client.post(
            base + "/audio-answers", data=fields, files={"audio": ("a.wav", wav_bytes())}
        )
        assert replay.json() == first.json()
        assert fake.calls == 1
        conflict = client.post(
            base + "/audio-answers", data=fields, files={"audio": ("a.wav", b"different")}
        )
        assert conflict.status_code == 409
        assert (
            client.get(base + "/prompt/audio", params={"prompt_id": prompt_id}).status_code == 409
        )
        assert (
            client.post(
                base + "/answers", json={**fields, "answer": "Use transactions."}
            ).status_code
            == 409
        )
