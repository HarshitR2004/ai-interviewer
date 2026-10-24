from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile

from backend.api.dependencies import preparation_service
from backend.api.errors import ErrorResponse
from backend.common.errors import InvalidInput
from backend.features.preparation.models import Preparation, PreparationInputs
from backend.features.preparation.service import PreparationService
from backend.features.resume_ingestion.service import ResumeUpload

router = APIRouter(
    prefix="/api/candidates",
    tags=["preparation"],
    responses={
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
Service = Annotated[PreparationService, Depends(preparation_service)]


@router.post("", response_model=Preparation, status_code=201)
async def submit(
    request: Request,
    service: Service,
    resume: Annotated[UploadFile, File()],
    job_description: Annotated[str, Form(min_length=40, max_length=12000)],
    duration: Annotated[int, Form()] = 45,
    seniority: Annotated[str, Form()] = "junior",
) -> Preparation:
    # Validate one resume upload and return the persisted profile and interview plan.
    try:
        form = await request.form()
        if (
            len([item for _, item in form.multi_items() if hasattr(item, "filename")]) != 1
            or len(form.getlist("resume")) != 1
        ):
            raise InvalidInput("Upload exactly one PDF resume.")
        inputs = PreparationInputs.model_validate(
            {
                "job_description": job_description,
                "settings": {
                    "duration": duration,
                    "seniority": seniority,
                },
            }
        )
        content = await resume.read(10 * 1024 * 1024 + 1)
        if len(content) > 10 * 1024 * 1024:
            raise InvalidInput("Please upload a PDF smaller than 10 MB.")
        upload = ResumeUpload(resume.filename or "", resume.content_type or "", content)
    finally:
        await resume.close()
    return await service.submit(upload, inputs)


@router.get("/{candidate_id}", response_model=Preparation)
async def get(candidate_id: str, service: Service) -> Preparation:
    # Reload a completed preparation from its saved documents.
    return await service.get(candidate_id)


@router.post("/{candidate_id}/interview", response_model=Preparation)
async def replan(candidate_id: str, body: PreparationInputs, service: Service) -> Preparation:
    # Regenerate the plan using the existing candidate profile.
    return await service.replan(candidate_id, body)
