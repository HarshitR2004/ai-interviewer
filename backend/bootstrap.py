"""Assemble the demo's concrete providers, document store, and session registry."""

import asyncio
from dataclasses import dataclass

from backend.integrations.llm.client import ChatCompletionsClient
from backend.integrations.llm.structured_generation import StructuredGeneration
from backend.integrations.voice.rooms import VoiceRooms
from backend.modules.live_interviews.reasoning import ModelReasoner
from backend.modules.live_interviews.service import LiveInterviewService
from backend.modules.live_interviews.sessions import SessionRegistry
from backend.modules.live_interviews.storage import JsonHistoryStore
from backend.modules.pre_interview.preparation.planning import InterviewPlanner
from backend.modules.pre_interview.preparation.service import PreparationService
from backend.modules.pre_interview.preparation.storage import MarkdownPreparationStore
from backend.modules.pre_interview.profiles.service import ProfileService
from backend.modules.pre_interview.resume_ingestion.pdf_extractor import PdfExtractor
from backend.settings import Settings


@dataclass
class Services:
    preparation: PreparationService
    live: LiveInterviewService
    voice: VoiceRooms | None = None
    model: ChatCompletionsClient | None = None
    live_model: ChatCompletionsClient | None = None
    agent_secret: str = "local-interview-agent-change-me"

    async def aclose(self) -> None:
        # Close provider clients when the application shuts down.
        await asyncio.gather(
            *(client.aclose() for client in (self.model, self.live_model, self.voice) if client is not None)
        )


def build_services(settings: Settings) -> Services:
    # Wire shared providers into preparation, live-session, and optional speech services.
    client = ChatCompletionsClient(settings.llm_base_url, settings.llm_model, settings.llm_api_key)
    generator = StructuredGeneration(client)
    preparation = PreparationService(
        MarkdownPreparationStore(settings.data_dir / "demo/candidates"),
        ProfileService(generator),
        InterviewPlanner(generator),
        PdfExtractor(),
    )
    live_client = ChatCompletionsClient(
        settings.llm_base_url, settings.live_llm_model or settings.llm_model,
        settings.llm_api_key,
        reasoning_effort="minimal" if "flash-lite" in (settings.live_llm_model or settings.llm_model) else "low",
    )
    live = LiveInterviewService(
        SessionRegistry(),
        preparation,
        ModelReasoner(live_client, timeout=settings.live_reasoning_timeout_sec),
        timeout=settings.live_reasoning_timeout_sec,
        history=JsonHistoryStore(settings.data_dir / "demo/interviews"),
        analysis_generator=StructuredGeneration(live_client),
    )
    return Services(
        preparation=preparation, live=live, voice=VoiceRooms(settings), model=client,
        live_model=live_client, agent_secret=settings.agent_secret.get_secret_value()
    )
