from backend.shared.ports import LanguageModel

from .models import Persona
from .prompts import PROFILE
from .validation import validate_persona


class ProfileService:
    def __init__(self, model: LanguageModel):
        self.model = model

    async def create(self, resume_text: str) -> Persona:
        allowed_sources = {"resume"}
        persona = await self.model.generate(
            PROFILE,
            {"resume": resume_text, "allowed_sources": sorted(allowed_sources)},
            Persona,
            lambda value: validate_persona(value, allowed_sources),
        )
        persona.source_references = ["resume"]
        persona.collection_status = {"resume": "processed"}
        return persona
