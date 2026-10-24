import hashlib

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, Response

from backend.features.live_interviews.models import (
    AnswerEvent,
    CreateSession,
    EndEvent,
    EngineError,
)
from backend.features.live_interviews.storage import digest

router = APIRouter(prefix="/api/live-sessions")


@router.post("", status_code=201)
async def create_session(body: CreateSession, request: Request):
    return await request.app.state.live_service.create(body)


@router.get("/{session_id}")
async def get_session(session_id: str, request: Request):
    return await request.app.state.live_service.get(session_id)


@router.post("/{session_id}/answers")
async def answer(session_id: str, body: AnswerEvent, request: Request):
    result = await request.app.state.live_service.answer(session_id, body)
    return JSONResponse(result, status_code=202 if result["status"] == "processing" else 200)


@router.post("/{session_id}/end")
async def end_session(session_id: str, body: EndEvent, request: Request):
    return await request.app.state.live_service.end(session_id, body)


def speech_client(request):
    client = request.app.state.speech_client
    if client is None:
        raise HTTPException(503, "Speech is disabled. Configure speech endpoints and enable it.")
    return client


@router.get("/{session_id}/prompt/audio")
async def prompt_audio(session_id: str, prompt_id: str, request: Request):
    client = speech_client(request)
    state = await request.app.state.live_service.get(session_id)
    prompt = state["current_prompt"]
    if not prompt or prompt["id"] != prompt_id:
        raise HTTPException(409, "This prompt is no longer current.")
    audio = await client.synthesize(prompt["text"])
    latest = await request.app.state.live_service.get(session_id)
    if not latest["current_prompt"] or latest["current_prompt"]["id"] != prompt_id:
        raise HTTPException(409, "Interview changed during speech generation.")
    return Response(
        audio,
        media_type="audio/wav",
        headers={"Cache-Control": "no-store", "X-Prompt-ID": prompt_id},
    )


@router.post("/{session_id}/audio-answers")
async def audio_answer(
    session_id: str,
    request: Request,
    audio: UploadFile = File(...),
    event_id: str = Form(..., min_length=1, max_length=128),
    prompt_id: str = Form(..., min_length=1, max_length=128),
    replaces_event_id: str | None = Form(None),
):
    client = speech_client(request)
    if request.app.state.live_service.reasoner is None:
        raise HTTPException(503, "Live reasoning is disabled. No answer was saved.")
    try:
        content = await audio.read(12 * 1024 * 1024 + 1)
    finally:
        await audio.close()
    if len(content) > 12 * 1024 * 1024:
        raise HTTPException(422, "Recording must be smaller than 12 MB.")
    service = request.app.state.live_service
    await service.expire()
    fingerprint = digest(
        {
            "prompt_id": prompt_id,
            "replaces_event_id": replaces_event_id,
            "sha256": hashlib.sha256(content).hexdigest(),
        }
    )
    result = await service.repository.claim_audio(
        session_id, event_id, prompt_id, fingerprint, service.clock()
    )
    if result is None:
        try:
            transcript = await client.transcribe(content)
            if not transcript["text"].strip():
                raise EngineError(422, "No speech was recognized. Record your answer again.")
            if len(transcript["text"]) > 16000:
                raise EngineError(422, "Recognized answer is too long.")
            event = AnswerEvent(
                event_id=event_id,
                prompt_id=prompt_id,
                answer=transcript["text"],
                replaces_event_id=replaces_event_id,
            )
            result = await service.answer(session_id, event, audio=True)
            result = await service.repository.complete_audio(
                session_id, event_id, {**result, "transcription": transcript}
            )
        except EngineError as exc:
            result = await service.repository.complete_audio(
                session_id,
                event_id,
                {"status": "failed", "detail": str(exc), "http_status": exc.status},
            )
    return JSONResponse(
        result,
        status_code=result.get("http_status", 202 if result["status"] == "processing" else 200),
    )
