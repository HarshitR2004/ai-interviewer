import asyncio
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError

from backend.features.collection.resume import MAX_PDF_BYTES, extract_resume
from backend.features.interviews.models import InterviewSettings, ReplanRequest
from backend.shared.errors import WorkflowError

router = APIRouter()
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")
SAMPLE_JD = """Software Engineer â€” Junior

Build and maintain backend services and APIs using Python. Work with relational databases, write automated tests, and collaborate through Git and code reviews.

Required competencies: Python fundamentals, API design, relational database design, testing and debugging.

We value clear technical reasoning, maintainable code, and the ability to explain project decisions and tradeoffs. Prior professional experience is not required."""


@router.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse(
        request=request, name="index.html", context={"sample_jd": SAMPLE_JD}
    )


def launch(request: Request, coroutine):
    task = asyncio.create_task(coroutine)
    request.app.state.tasks.add(task)
    task.add_done_callback(request.app.state.tasks.discard)


@router.post("/api/candidates", status_code=202)
async def create_candidate(
    request: Request,
    resume: UploadFile = File(...),
    job_description: str = Form(..., min_length=40, max_length=12000),
    duration: int = Form(45),
    seniority: str = Form("junior"),
    interview_type: str = Form("mixed"),
):
    try:
        settings = InterviewSettings(
            duration=duration, seniority=seniority, interview_type=interview_type
        )
        filename = resume.filename or ""
        if (
            not filename.lower().endswith(".pdf")
            or "/" in filename
            or "\\" in filename
            or ":" in filename
            or any(ord(char) < 32 for char in filename)
        ):
            raise WorkflowError("Please upload a PDF file with a plain .pdf filename.")
        if resume.content_type not in {"application/pdf", "application/octet-stream"}:
            raise WorkflowError("Please upload a PDF resume.")
        form = await request.form()
        uploads = [item for _, item in form.multi_items() if hasattr(item, "filename")]
        if len(uploads) != 1 or len(form.getlist("resume")) != 1:
            raise WorkflowError("Upload exactly one PDF resume.")
        content = await resume.read(MAX_PDF_BYTES + 1)
        if len(content) > MAX_PDF_BYTES:
            raise WorkflowError("Please upload a PDF smaller than 10 MB.")
        text = await asyncio.to_thread(extract_resume, content)
    except (ValueError, WorkflowError) as exc:
        message = (
            "Check the interview settings and try again."
            if isinstance(exc, ValidationError)
            else str(exc)
        )
        raise HTTPException(422, message) from exc
    finally:
        await resume.close()
    service = request.app.state.service
    candidate_id = service.store.create()
    path = service.store.candidate(candidate_id)
    service.store.write(path / "inputs/resume.pdf", content)
    service.store.write(path / "inputs/job_description.txt", job_description)
    service.store.json(path / "inputs/settings.json", settings.model_dump())
    service.active.add(candidate_id)
    launch(
        request,
        service.prepare(candidate_id, text, job_description, settings),
    )
    return {"candidate_id": candidate_id}


@router.get("/api/candidates/{candidate_id}/status")
async def candidate_status(candidate_id: str, request: Request):
    try:
        return request.app.state.service.store.status(candidate_id)
    except FileNotFoundError:
        raise HTTPException(404, "This preparation could not be found.")


@router.post("/api/candidates/{candidate_id}/interview", status_code=202)
async def replan(candidate_id: str, body: ReplanRequest, request: Request):
    service = request.app.state.service
    try:
        path = service.store.candidate(candidate_id)
    except FileNotFoundError:
        raise HTTPException(404, "This preparation could not be found.")
    if candidate_id in service.active:
        raise HTTPException(409, "This preparation is still in progress.")
    if not (path / "structured/persona.json").is_file():
        raise HTTPException(409, "Please finish preparing the candidate profile first.")
    service.active.add(candidate_id)
    service.update(
        candidate_id,
        "queued",
        "Your interview update is queued.",
        service.store.status(candidate_id).warnings,
    )
    settings = InterviewSettings(**body.model_dump(exclude={"job_description"}))
    launch(request, service.replan(candidate_id, body.job_description, settings))
    return {"candidate_id": candidate_id}
