from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Response, UploadFile

from backend.api.dependencies import audio_service, live_service
from backend.api.errors import ErrorResponse
from backend.modules.live_interviews.audio_service import AudioInterviewService
from backend.modules.live_interviews.models import (
    AnswerInput,
    AnswerResult,
    CreateSession,
    PublicSession,
)
from backend.modules.live_interviews.service import LiveInterviewService

router = APIRouter(
    prefix="/api/live-sessions",
    tags=["live interviews"],
    responses={
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
Live = Annotated[LiveInterviewService, Depends(live_service)]
Audio = Annotated[AudioInterviewService, Depends(audio_service)]


@router.post("", response_model=PublicSession, status_code=201)
async def create(body: CreateSession, service: Live) -> PublicSession:
    # Start an independent live session from a saved preparation.
    return await service.create(body.candidate_id)


@router.get("/{session_id}", response_model=PublicSession)
async def get(session_id: str, service: Live) -> PublicSession:
    # Return public session progress after checking expiry.
    return service.get(session_id)


@router.post("/{session_id}/answers", response_model=AnswerResult)
async def answer(session_id: str, body: AnswerInput, service: Live) -> AnswerResult:
    # Assess a text answer and return the next interview prompt.
    return await service.answer(session_id, body)


@router.post("/{session_id}/end", response_model=PublicSession)
async def end(session_id: str, service: Live) -> PublicSession:
    # Close the session and stop accepting answers.
    return service.end(session_id)


@router.get(
    "/{session_id}/prompt/audio",
    response_class=Response,
    responses={200: {"content": {"audio/wav": {"schema": {"type": "string", "format": "binary"}}}}},
)
async def prompt_audio(session_id: str, prompt_id: str, service: Audio) -> Response:
    # Synthesize the current prompt without caching candidate-specific audio.
    return Response(
        await service.prompt_audio(session_id, prompt_id),
        media_type="audio/wav",
        headers={"Cache-Control": "no-store", "X-Prompt-ID": prompt_id},
    )


@router.post("/{session_id}/audio-answers", response_model=AnswerResult)
async def audio_answer(
    session_id: str,
    service: Audio,
    audio: Annotated[UploadFile, File()],
    prompt_id: Annotated[str, Form(min_length=1, max_length=128)],
) -> AnswerResult:
    # Transcribe an uploaded answer and run the same assessment flow as text.
    try:
        content = await audio.read(12 * 1024 * 1024 + 1)
    finally:
        await audio.close()
    return await service.answer(session_id, content, prompt_id)
