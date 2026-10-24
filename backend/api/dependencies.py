from typing import Annotated, cast

from fastapi import Depends, Request

from backend.bootstrap import Services
from backend.modules.live_interviews.audio_service import AudioInterviewService
from backend.modules.live_interviews.service import LiveInterviewService
from backend.modules.preparation.service import PreparationService


def services(request: Request) -> Services:
    return cast(Services, request.app.state.services)


def preparation_service(container: Annotated[Services, Depends(services)]) -> PreparationService:
    return container.preparation


def live_service(container: Annotated[Services, Depends(services)]) -> LiveInterviewService:
    return container.live


def audio_service(container: Annotated[Services, Depends(services)]) -> AudioInterviewService:
    return container.audio
