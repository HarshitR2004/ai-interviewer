import asyncio
import json
import sqlite3

import httpx
import pytest
from fastapi.testclient import TestClient

from backend.features.live_interviews.models import (
    AnswerEvent,
    CreateSession,
    Decision,
    EndEvent,
    EngineError,
)
from backend.features.live_interviews.reasoning import ModelReasoner
from backend.features.live_interviews.service import LiveInterviewService
from backend.features.live_interviews.source import LocalPlanSource
from backend.features.live_interviews.storage import SQLiteRepository
from backend.main import create_app
from backend.shared.config import Settings
from backend.shared.llm import ChatCompletionsClient


class Source:
    def __init__(self, plan):
        self.plan = plan

    async def load(self, candidate_id):
        return {"plan": self.plan.model_dump(), "settings": {"duration": 45}, "plan_version": "1"}


class FakeReasoner:
    def __init__(self, action="advance"):
        self.calls = 0
        self.action = action

    async def assess(self, snapshot, answer):
        self.calls += 1
        return Decision(action=self.action, next_question="Explain your reasoning more clearly.")


class BlockingReasoner(FakeReasoner):
    def __init__(self):
        super().__init__()
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def assess(self, snapshot, answer):
        self.calls += 1
        self.started.set()
        await self.release.wait()
        return Decision(action="advance")


async def engine(tmp_path, plan, reasoner=None):
    now = [1000.0]
    service = LiveInterviewService(
        SQLiteRepository(tmp_path / "live.sqlite3"),
        Source(plan),
        reasoner,
        clock=lambda: now[0],
    )
    await service.initialize()
    state = await service.create(CreateSession(candidate_id="a" * 32, event_id="create"))
    return service, state, now


def event(state, event_id="answer", **kwargs):
    return AnswerEvent(
        event_id=event_id,
        prompt_id=state["current_prompt"]["id"],
        answer="I would use a persistent idempotency key.",
        **kwargs,
    )


async def test_progression_and_no_rubric_leak(tmp_path, plan):
    reasoner = FakeReasoner("clarify")
    service, state, _ = await engine(tmp_path, plan, reasoner)
    sid = state["session_id"]
    for index in range(3):
        result = await service.answer(sid, event(state, str(index)))
        state = result["session"]
    assert result["action"] == "advance"  # Third probe exceeds limit.
    assert state["question_number"] == 2
    reasoner.action = "advance"
    result = await service.answer(sid, event(state, "last"))
    assert result["session"]["status"] == "completed"
    assert len(result["session"]["progression"]) == 4
    assert "scoring_guidance" not in json.dumps(result)
    assert "missing_evidence" not in json.dumps(result)


async def test_duplicate_and_conflicting_events(tmp_path, plan):
    reasoner = FakeReasoner()
    service, state, _ = await engine(tmp_path, plan, reasoner)
    answer = event(state)
    first = await service.answer(state["session_id"], answer)
    assert await service.answer(state["session_id"], answer) == first
    assert reasoner.calls == 1
    with pytest.raises(EngineError, match="different input"):
        await service.answer(state["session_id"], answer.model_copy(update={"answer": "Changed"}))
    repeated = await service.create(CreateSession(candidate_id="a" * 32, event_id="create"))
    assert repeated["session_id"] == state["session_id"]


async def test_pending_duplicate_and_correction_discard_stale_result(tmp_path, plan):
    reasoner = BlockingReasoner()
    service, state, _ = await engine(tmp_path, plan, reasoner)
    sid = state["session_id"]
    answer = event(state)
    original = asyncio.create_task(service.answer(sid, answer))
    await reasoner.started.wait()
    assert await service.answer(sid, answer) == {"status": "processing"}
    with pytest.raises(EngineError, match="already being assessed"):
        await service.answer(sid, event(state, "another"))
    correction = asyncio.create_task(
        service.answer(sid, event(state, "correction", replaces_event_id="answer"))
    )
    # Await the committed correction claim, not a timing-dependent sleep.
    for _ in range(100):
        current = await service.repository.get(sid)
        if current["answer_version"] == 2:
            break
        await asyncio.sleep(0)
    assert current["answer_version"] == 2
    reasoner.release.set()
    old, new = await asyncio.gather(original, correction)
    assert old["status"] == "superseded"
    assert new["session"]["question_number"] == 2
    assert len(new["session"]["progression"]) == 1
    with pytest.raises(EngineError, match="no longer current"):
        await service.answer(sid, event(state, "too-late", replaces_event_id="correction"))


async def test_end_wins_over_pending_assessment(tmp_path, plan):
    reasoner = BlockingReasoner()
    service, state, _ = await engine(tmp_path, plan, reasoner)
    sid = state["session_id"]
    pending = asyncio.create_task(service.answer(sid, event(state)))
    await reasoner.started.wait()
    ended = await service.end(sid, EndEvent(event_id="end"))
    assert await service.end(sid, EndEvent(event_id="end")) == ended
    reasoner.release.set()
    assert (await pending)["status"] == "cancelled"
    assert (await service.get(sid))["status"] == "completed"


async def test_time_limits_and_fallback(tmp_path, plan):
    reasoner = BlockingReasoner()
    service, state, now = await engine(tmp_path, plan, reasoner)
    service.timeout = 0.01
    result = await service.answer(state["session_id"], event(state))
    assert result["assessment_unavailable"] is True
    assert (
        result["session"]["current_prompt"]["text"] == plan.sections[0].questions[0].follow_ups[0]
    )
    assert (await service.repository.get(state["session_id"]))["evidence"] == []
    reasoner.release.set()
    now[0] += 25 * 60
    state = result["session"]
    result = await service.answer(state["session_id"], event(state, "after-section"))
    assert result["session"]["question_number"] == 2
    now[0] += 20 * 60
    assert (await service.get(state["session_id"]))["status"] == "completed"


async def test_restart_and_disabled_provider(tmp_path, plan):
    service, state, _ = await engine(tmp_path, plan)
    with pytest.raises(EngineError, match="disabled"):
        await service.answer(state["session_id"], event(state))
    assert (await service.repository.get(state["session_id"]))["answers"] == []
    await service.initialize()
    assert (await service.get(state["session_id"]))["status"] == "interrupted"


async def test_commit_rolls_back_all_records(tmp_path, plan):
    service, state, _ = await engine(tmp_path, plan, FakeReasoner())
    with sqlite3.connect(service.repository.path) as db:
        db.execute("""CREATE TRIGGER fail_command BEFORE INSERT ON commands
                      BEGIN SELECT RAISE(ABORT, 'simulated failure'); END""")
    with pytest.raises(sqlite3.IntegrityError):
        await service.answer(state["session_id"], event(state))
    stored = await service.repository.get(state["session_id"])
    assert stored["question_index"] == 0
    assert stored["version"] == 2  # Answer acceptance committed; decision did not.
    with sqlite3.connect(service.repository.path) as db:
        assert db.execute("SELECT count(*) FROM decisions").fetchone()[0] == 0
        assert db.execute("SELECT status FROM events").fetchone()[0] == "processing"


async def test_configurable_adapter_with_fake_http_transport(tmp_path, plan):
    service, state, _ = await engine(tmp_path, plan, FakeReasoner())
    snapshot, _ = await service.repository.accept(state["session_id"], event(state), 1000)
    calls = []

    def handler(request):
        body = json.loads(request.content)
        calls.append(body)
        assert request.url.path == "/v1/chat/completions"
        assert request.url.host == "llm.example"
        assert request.headers["authorization"] == "Bearer test-key"
        assert body["stream"] is False
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": '{"action":"advance"}'}, "finish_reason": "stop"}
                ]
            },
        )

    adapter = ModelReasoner(
        ChatCompletionsClient(
            "https://llm.example/v1",
            "test-model",
            "test-key",
            transport=httpx.MockTransport(handler),
        )
    )
    assert (await adapter.assess(snapshot, "Answer")).action == "advance"
    assert len(calls) == 1


def test_api_disabled_default_and_end(tmp_path, plan):
    service = LiveInterviewService(SQLiteRepository(tmp_path / "test.sqlite3"), Source(plan), None)
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
        response = client.post(
            "/api/live-sessions", json={"candidate_id": "a" * 32, "event_id": "start"}
        )
        assert response.status_code == 201
        state = response.json()
        url = f"/api/live-sessions/{state['session_id']}"
        assert client.get(url).status_code == 200
        assert client.post(url + "/answers", json=event(state).model_dump()).status_code == 503
        assert (
            client.post(url + "/end", json={"event_id": "end"}).json()["session"]["status"]
            == "completed"
        )
        assert client.get("/api/live-sessions/missing").status_code == 404


async def test_plan_source_validates_snapshot_and_preparation_state(tmp_path, plan):
    candidate_id = "b" * 32
    path = tmp_path / candidate_id
    (path / "structured").mkdir(parents=True)
    (path / "inputs").mkdir()
    (path / "status.json").write_text('{"state":"completed"}')
    (path / "structured/interview.json").write_text(plan.model_dump_json())
    (path / "inputs/settings.json").write_text('{"duration":45}')
    active = set()
    source = LocalPlanSource(tmp_path, active)
    snapshot = await source.load(candidate_id)
    assert snapshot["plan"]["role"] == plan.role
    active.add(candidate_id)
    with pytest.raises(EngineError, match="still running"):
        await source.load(candidate_id)


async def test_simultaneous_duplicate_claims_only_assess_once(tmp_path, plan):
    reasoner = FakeReasoner()
    service, state, _ = await engine(tmp_path, plan, reasoner)
    answer = event(state)
    results = await asyncio.gather(
        service.answer(state["session_id"], answer),
        service.answer(state["session_id"], answer),
    )
    assert reasoner.calls == 1
    assert any(result["status"] == "completed" for result in results)
    stored = await service.repository.get(state["session_id"])
    assert len(stored["answers"]) == 1
    assert len(stored["progression"]) == 1


async def test_invalid_assessment_falls_back_without_evidence(tmp_path, plan):
    class InvalidReasoner:
        async def assess(self, snapshot, answer):
            return {"action": "invented-action", "evidence": ["Unsupported"]}

    service, state, _ = await engine(tmp_path, plan, InvalidReasoner())
    result = await service.answer(state["session_id"], event(state))
    assert result["assessment_unavailable"] is True
    assert result["action"] == "follow_up"
    assert (await service.repository.get(state["session_id"]))["evidence"] == []


def test_api_offline_interview_progression(tmp_path, plan):
    service = LiveInterviewService(
        SQLiteRepository(tmp_path / "api.sqlite3"), Source(plan), FakeReasoner()
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
        state = client.post(
            "/api/live-sessions", json={"candidate_id": "a" * 32, "event_id": "create"}
        ).json()
        url = f"/api/live-sessions/{state['session_id']}/answers"
        body = event(state).model_dump()
        first = client.post(url, json=body)
        assert first.status_code == 200
        assert first.json()["session"]["question_number"] == 2
        assert client.post(url, json=body).json() == first.json()
        assert client.post(url, json={**body, "answer": "Changed"}).status_code == 409
        assert client.post(url, json={**body, "answer": " "}).status_code == 422
