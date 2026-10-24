from typing import Protocol

from pydantic import BaseModel, Field


class Transcript(BaseModel):
    text: str = Field(min_length=1, max_length=16000)


class Transcriber(Protocol):
    async def transcribe(self, content: bytes) -> Transcript: ...


class Synthesizer(Protocol):
    async def synthesize(self, text: str) -> bytes: ...
