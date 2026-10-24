import time

import pytest
from conftest import FakeModel, make_service
from fastapi.testclient import TestClient

from backend.features.preparation.storage import LocalStore
from backend.main import create_app
from backend.shared.config import Settings


def make_client(tmp_path, persona, plan):
    store = LocalStore(tmp_path)
    service = make_service(store, FakeModel(persona, plan))
    return TestClient(
        create_app(
            Settings(
                _env_file=None,
                data_dir=tmp_path,
                llm_base_url="https://llm.example/v1",
                llm_model="test-model",
            ),
            service,
        )
    )


def test_submit_and_status(tmp_path, persona, plan, resume_pdf):
    with make_client(tmp_path, persona, plan) as client:
        response = client.post(
            "/api/candidates",
            files={"resume": ("resume.pdf", resume_pdf, "application/pdf")},
            data={
                "job_description": "Build Python APIs with database design and testing.",
            },
        )
        assert response.status_code == 202
        candidate = response.json()["candidate_id"]
        for _ in range(100):
            status = client.get(f"/api/candidates/{candidate}/status").json()
            if status["state"] in {"completed", "failed"}:
                break
            time.sleep(0.01)
        assert status["state"] == "completed"
        assert (tmp_path / candidate / "inputs/resume.pdf").read_bytes() == resume_pdf
        updated = client.post(
            f"/api/candidates/{candidate}/interview",
            json={"job_description": "Updated Python API role with database and testing focus."},
        )
        assert updated.status_code == 202


def test_validation_and_ui_boundary(tmp_path, persona, plan):
    with make_client(tmp_path, persona, plan) as client:
        html = client.get("/").text
        for text in ("OpenRouter", "flint-v1.0", "persona.json", "Download", "Backend"):
            assert text not in html
        assert 'aria-live="polite"' in html
        assert 'for="resume"' in html
        assert 'name="github"' not in html
        assert client.get("/static/styles.css").status_code == 200
        assert client.get("/api/candidates/not-a-candidate/status").status_code == 404
        assert (
            client.post(
                "/api/candidates",
                files={"resume": ("x.pdf", b"not pdf")},
                data={"job_description": "A sufficient job description for this technical role."},
            ).status_code
            == 422
        )
        response = client.post("/api/candidates", data={"resume": "private-input"})
        assert response.status_code == 422
        assert "private-input" not in response.text


@pytest.mark.parametrize(
    "filename,mime,content",
    [
        ("resume.exe", "application/pdf", None),
        ("../resume.pdf", "application/pdf", None),
        ("resume.pdf", "text/html", None),
        ("resume.pdf", "application/pdf", b"%PDF-1.7\nspoofed\n%%EOF"),
    ],
)
def test_upload_validation_does_not_persist_files(
    tmp_path, persona, plan, resume_pdf, filename, mime, content
):
    with make_client(tmp_path, persona, plan) as client:
        response = client.post(
            "/api/candidates",
            files={"resume": (filename, content if content is not None else resume_pdf, mime)},
            data={"job_description": "Build Python APIs with database design and testing."},
        )
        assert response.status_code == 422
        assert not list(tmp_path.glob("*/inputs"))


def test_rejects_active_pdf_before_storage(tmp_path, persona, plan, resume_pdf):
    from io import BytesIO

    from pypdf import PdfReader, PdfWriter

    writer = PdfWriter()
    writer.clone_document_from_reader(PdfReader(BytesIO(resume_pdf)))
    writer.add_js("app.alert('synthetic')")
    output = BytesIO()
    writer.write(output)
    with make_client(tmp_path, persona, plan) as client:
        response = client.post(
            "/api/candidates",
            files={"resume": ("resume.pdf", output.getvalue(), "application/pdf")},
            data={"job_description": "Build Python APIs with database design and testing."},
        )
        assert response.status_code == 422
        assert not list(tmp_path.glob("*/inputs"))


def test_rejects_multiple_files(tmp_path, persona, plan, resume_pdf):
    with make_client(tmp_path, persona, plan) as client:
        response = client.post(
            "/api/candidates",
            files=[
                ("resume", ("one.pdf", resume_pdf, "application/pdf")),
                ("extra", ("two.pdf", resume_pdf, "application/pdf")),
            ],
            data={"job_description": "Build Python APIs with database design and testing."},
        )
        assert response.status_code == 422
        assert not list(tmp_path.glob("*/inputs"))
