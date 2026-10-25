import pytest
from fastapi.testclient import TestClient

from backend.bootstrap import Services
from backend.main import create_app
from backend.modules.live_interviews.service import LiveInterviewService
from backend.modules.live_interviews.sessions import SessionRegistry
from backend.modules.live_interviews.storage import JsonHistoryStore
from backend.modules.pre_interview.preparation.storage import MarkdownPreparationStore
from tests.fakes import FakeModel, FakeReasoner, make_preparation

JD = "Build Python APIs with database design and testing."


def client_for(tmp_path, persona, plan, speech=None, reasoner=True):
    prep = make_preparation(
        MarkdownPreparationStore(tmp_path / "demo/candidates"), FakeModel(persona, plan)
    )
    live = LiveInterviewService(
        SessionRegistry(),
        prep,
        FakeReasoner() if reasoner else None,
        history=JsonHistoryStore(tmp_path / "demo/interviews"),
    )
    services = Services(prep, live)
    return TestClient(create_app(services))


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
    from backend.modules.pre_interview.resume_ingestion.pdf_extractor import MAX_PDF_BYTES

    with client_for(tmp_path, persona, plan) as client:
        result = client.post(
            "/api/candidates",
            files={"resume": ("resume.pdf", b"x" * (MAX_PDF_BYTES + 1), "application/pdf")},
            data={"job_description": JD},
        )
        assert result.status_code == 422
        assert result.json()["detail"] == "Please upload a PDF of at most 10 MB."
        assert not list((tmp_path / "demo/candidates").glob("*"))
