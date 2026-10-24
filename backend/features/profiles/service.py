from backend.integrations.llm.contracts import StructuredGenerator

from .models import CandidateProfile
from .prompts import PROFILE
from .validation import validate_profile


class ProfileService:
    def __init__(self, model: StructuredGenerator):
        self.model = model

    async def create(self, resume_text: str) -> CandidateProfile:
        allowed_sources = {"resume"}
        persona = await self.model.generate(
            PROFILE,
            {"resume": resume_text, "allowed_sources": sorted(allowed_sources)},
            CandidateProfile,
            lambda value: validate_profile(value, allowed_sources),
        )
        persona.source_references = ["resume"]
        persona.collection_status = {"resume": "processed"}
        return persona
