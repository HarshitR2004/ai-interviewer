"""Assemble the demo's concrete providers, document store, and session registry."""

import asyncio
from dataclasses import dataclass

from backend.integrations.llm.client import ChatCompletionsClient
from backend.integrations.llm.structured_generation import StructuredGeneration
from backend.integrations.speech.client import SpeechClient
from backend.modules.live_interviews.audio_service import AudioInterviewService
from backend.modules.live_interviews.reasoning import ModelReasoner
from backend.modules.live_interviews.service import LiveInterviewService
from backend.modules.live_interviews.sessions import SessionRegistry
from backend.modules.pre_interview.interview_planning.service import InterviewService
from backend.modules.pre_interview.preparation.service import PreparationService
from backend.modules.pre_interview.preparation.storage import MarkdownPreparationStore
from backend.modules.pre_interview.profiles.service import ProfileService
from backend.modules.pre_interview.resume_ingestion.pdf_extractor import PdfExtractor
from backend.modules.pre_interview.resume_ingestion.service import ResumeIngestionService
from backend.settings import Settings


@dataclass
class Services:
    preparation: PreparationService
    live: LiveInterviewService
    audio: AudioInterviewService
    model: ChatCompletionsClient | None = None
    speech: SpeechClient | None = None

    async def aclose(self) -> None:
        # Close provider clients when the application shuts down.
        await asyncio.gather(
            *(client.aclose() for client in (self.model, self.speech) if client is not None)
        )


def build_services(settings: Settings) -> Services:
    # Wire shared providers into preparation, live-session, and optional speech services.
    client = ChatCompletionsClient(settings.llm_base_url, settings.llm_model, settings.llm_api_key)
    generator = StructuredGeneration(client)
    preparation = PreparationService(
        MarkdownPreparationStore(settings.data_dir / "demo/candidates"),
        ProfileService(generator),
        InterviewService(generator),
        ResumeIngestionService(PdfExtractor()),
    )
    live = LiveInterviewService(
        SessionRegistry(),
        preparation,
        ModelReasoner(client, timeout=settings.live_reasoning_timeout_sec)
        if settings.live_reasoning_enabled
        else None,
        timeout=settings.live_reasoning_timeout_sec,
    )
    speech = (
        SpeechClient(
            settings.stt_base_url,
            settings.tts_base_url,
            stt_api_key=settings.stt_api_key,
            tts_api_key=settings.tts_api_key,
            timeout=settings.speech_timeout_sec,
        )
        if settings.speech_enabled
        else None
    )
    audio = AudioInterviewService(
        live, speech if settings.stt_base_url else None, speech if settings.tts_base_url else None
    )
    return Services(preparation, live, audio, client, speech)
