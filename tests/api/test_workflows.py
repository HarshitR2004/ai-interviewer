import pytest
from fastapi.testclient import TestClient

from backend.bootstrap import Services
from backend.main import create_app
from backend.modules.live_interviews.audio_service import AudioInterviewService
from backend.modules.live_interviews.service import LiveInterviewService
from backend.modules.live_interviews.sessions import SessionRegistry
from backend.modules.preparation.storage import MarkdownPreparationStore
from backend.settings import Settings
from tests.factories import wav_bytes
from tests.fakes import FakeModel, FakeReasoner, FakeSpeech, make_preparation

JD = "Build Python APIs with database design and testing."


def client_for(tmp_path, persona, plan, speech=None, reasoner=True):
    def factory(config):
        prep = make_preparation(
            MarkdownPreparationStore(config.data_dir / "demo/candidates"), FakeModel(persona, plan)
        )
        live = LiveInterviewService(SessionRegistry(), prep, FakeReasoner() if reasoner else None)
        return Services(prep, live, AudioInterviewService(live, speech, speech))

    settings = Settings(
        _env_file=None, data_dir=tmp_path, llm_base_url="https://llm.example/v1", llm_model="test"
    )
    return TestClient(create_app(settings, service_factory=factory))


def prepare(client, resume_pdf):
    result = client.post(
        "/api/candidates",
        files={"resume": ("resume.pdf", resume_pdf, "application/pdf")},
        data={"job_description": JD},
    )
    assert result.status_code == 201, result.text
    return result.json()


def session(client, candidate_id):
    result = client.post("/api/live-sessions", json={"candidate_id": candidate_id})
    assert result.status_code == 201, result.text
    return result.json()


def test_end_to_end_markdown_reload_and_lost_live_sessions(tmp_path, persona, plan, resume_pdf):
    legacy = tmp_path / "v2/keep.json"
    legacy.parent.mkdir()
    legacy.write_bytes(b"untouched")
    with client_for(tmp_path, persona, plan) as client:
        prep = prepare(client, resume_pdf)
        candidate = prep["candidate_id"]
        assert client.get(f"/api/candidates/{candidate}").json() == prep
        state = session(client, candidate)
        base = f"/api/live-sessions/{state['session_id']}"
        body = {"prompt_id": state["current_prompt"]["id"], "answer": "Use transactions."}
        first = client.post(base + "/answers", json=body)
        assert first.status_code == 200, first.text
        assert first.json()["session"]["question_number"] == 2
        assert "scoring_guidance" not in first.text and "strong_answer_signals" not in first.text
        assert client.post(base + "/answers", json=body).status_code == 409
        assert client.post(base + "/answers", json={**body, "answer": " "}).status_code == 422
        assert client.post(base + "/end").json()["status"] == "completed"
        updated = client.post(
            f"/api/candidates/{candidate}/interview",
            json={"job_description": JD + " Updated.", "settings": {"duration": 30}},
        )
        assert updated.status_code == 200 and updated.json()["settings"]["duration"] == 30
    with client_for(tmp_path, persona, plan) as client:
        assert client.get(f"/api/candidates/{candidate}").json() == updated.json()
        assert client.get(base).status_code == 404
        session(client, candidate)
    assert legacy.read_bytes() == b"untouched"
    assert {p.name for p in (tmp_path / "demo/candidates" / candidate).iterdir()} == {
        "resume.pdf",
        "persona.md",
        "interview-plan.md",
    }
    assert not list((tmp_path / "demo").rglob("*.json"))


def test_api_only_and_openapi(tmp_path, persona, plan):
    with client_for(tmp_path, persona, plan) as client:
        for url in ["/", "/static/styles.css", "/docs", "/redoc"]:
            assert client.get(url).status_code == 404
        spec = client.get("/openapi.json").json()
        assert len(spec["paths"]) == 9
        assert "/api/candidates/{candidate_id}/status" not in spec["paths"]
        assert "SessionState" not in spec["components"]["schemas"]
        assert "event_id" not in str(spec) and "replaces_event_id" not in str(spec)


@pytest.mark.parametrize(
    "filename,mime,payload",
    [
        ("resume.exe", "application/pdf", None),
        ("../resume.pdf", "application/pdf", None),
        ("resume.pdf", "text/html", None),
        ("resume.pdf", "application/pdf", b"%PDF-1.7\nspoofed\n%%EOF"),
    ],
)
def test_bad_uploads_do_not_create_candidates(
    tmp_path, persona, plan, resume_pdf, filename, mime, payload
):
    with client_for(tmp_path, persona, plan) as client:
        result = client.post(
            "/api/candidates",
            files={"resume": (filename, resume_pdf if payload is None else payload, mime)},
            data={"job_description": JD},
        )
        assert result.status_code == 422
        assert not list((tmp_path / "demo/candidates").glob("*"))


def test_multiple_files_and_private_validation(tmp_path, persona, plan, resume_pdf):
    with client_for(tmp_path, persona, plan) as client:
        result = client.post(
            "/api/candidates",
            files=[
                ("resume", ("one.pdf", resume_pdf, "application/pdf")),
                ("extra", ("two.pdf", resume_pdf, "application/pdf")),
            ],
            data={"job_description": JD},
        )
        assert result.status_code == 422
        assert client.get("/api/candidates/missing").status_code == 404
        invalid = client.post("/api/candidates", data={"resume": "private-input"})
        assert invalid.status_code == 422 and "private-input" not in invalid.text


def test_oversized_pdf_is_rejected(tmp_path, persona, plan):
    from backend.modules.resume_ingestion.pdf_extractor import MAX_PDF_BYTES

    with client_for(tmp_path, persona, plan) as client:
        result = client.post(
            "/api/candidates",
            files={"resume": ("resume.pdf", b"x" * (MAX_PDF_BYTES + 1), "application/pdf")},
            data={"job_description": JD},
        )
        assert result.status_code == 422
        assert result.json()["detail"] == "Please upload a PDF of at most 10 MB."
        assert not list((tmp_path / "demo/candidates").glob("*"))


def test_audio_and_disabled_capabilities(tmp_path, persona, plan, resume_pdf):
    speech = FakeSpeech()
    with client_for(tmp_path, persona, plan, speech=speech) as client:
        state = session(client, prepare(client, resume_pdf)["candidate_id"])
        base = f"/api/live-sessions/{state['session_id']}"
        prompt = state["current_prompt"]["id"]
        assert (
            client.get(base + "/prompt/audio", params={"prompt_id": prompt}).content == wav_bytes()
        )
        response = client.post(
            base + "/audio-answers",
            data={"prompt_id": prompt},
            files={"audio": ("answer.wav", wav_bytes())},
        )
        assert response.status_code == 200, response.text
        assert response.json()["transcription"]["text"]
        assert response.json()["session"]["question_number"] == 2
        assert client.get(base + "/prompt/audio", params={"prompt_id": prompt}).status_code == 409
    with client_for(tmp_path, persona, plan, reasoner=False) as client:
        state = session(client, prepare(client, resume_pdf)["candidate_id"])
        base = f"/api/live-sessions/{state['session_id']}"
        assert (
            client.post(
                base + "/answers",
                json={"prompt_id": state["current_prompt"]["id"], "answer": "Use transactions."},
            ).status_code
            == 503
        )
        assert (
            client.get(
                base + "/prompt/audio", params={"prompt_id": state["current_prompt"]["id"]}
            ).status_code
            == 503
        )
