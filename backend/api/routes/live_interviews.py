import asyncio
import secrets
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException

from backend.api.dependencies import live_service, services
from backend.bootstrap import Services
from backend.common.errors import Conflict, Unavailable
from backend.modules.live_interviews.models import (
    AgentEvent,
    AnswerResult,
    CreateSession,
    PublicSession,
    TurnInput,
)
from backend.modules.live_interviews.service import LiveInterviewService

router = APIRouter(prefix="/api/live-sessions", tags=["live interviews"])
Live = Annotated[LiveInterviewService, Depends(live_service)]
Container = Annotated[Services, Depends(services)]


def agent_only(container: Container, x_agent_secret: Annotated[str, Header()] = "") -> None:
    if not secrets.compare_digest(x_agent_secret, container.agent_secret):
        raise HTTPException(401, "Agent authentication required.")


@router.post("", response_model=PublicSession, status_code=201)
async def create(body: CreateSession, service: Live) -> PublicSession:
    return await service.create(body.candidate_id)


@router.get("/{session_id}", response_model=PublicSession)
async def get(session_id: str, service: Live) -> PublicSession:
    return service.get(session_id)


@router.post("/{session_id}/voice")
async def voice(session_id: str, service: Live, container: Container) -> dict[str, str]:
    if service.get(session_id).status not in {"waiting", "active"}:
        raise Conflict("This interview has ended. Start a new interview.")
    if container.voice is None:
        raise Unavailable("Voice transport is not configured.")
    return await container.voice.connect(session_id)


@router.post("/{session_id}/end", response_model=PublicSession)
async def end(session_id: str, service: Live, container: Container) -> PublicSession:
    result = service.end(session_id)
    if container.voice:
        await container.voice.release(session_id)
    return result


@router.get("/{session_id}/history")
async def history(session_id: str, service: Live) -> dict[str, object]:
    return service.history(session_id)


@router.get("/{session_id}/agent", dependencies=[Depends(agent_only)])
async def agent_state(session_id: str, service: Live) -> PublicSession:
    return service.agent_state(session_id)


@router.post("/{session_id}/agent/events", dependencies=[Depends(agent_only)])
async def agent_event(session_id: str, body: AgentEvent, service: Live) -> PublicSession:
    return service.event(session_id, body)


@router.post("/{session_id}/agent/turns", dependencies=[Depends(agent_only)])
async def turn(session_id: str, body: TurnInput, service: Live) -> AnswerResult:
    try:
        return await service.answer_from_transcript(session_id, body)
    except asyncio.CancelledError as exc:
        raise Conflict("This turn was cancelled by continued speech or session end.") from exc
