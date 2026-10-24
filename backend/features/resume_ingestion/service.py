import asyncio
from dataclasses import dataclass
from typing import Protocol

from backend.common.errors import InvalidInput


@dataclass(frozen=True)
class ResumeUpload:
    filename: str
    content_type: str
    content: bytes


class ResumeExtractor(Protocol):
    def extract(self, content: bytes) -> str: ...


class ResumeIngestionService:
    def __init__(self, extractor: ResumeExtractor):
        self.extractor = extractor

    async def extract(self, upload: ResumeUpload) -> str:
        name = upload.filename
        if (
            not name.lower().endswith(".pdf")
            or any(char in name for char in "/\\:")
            or any(ord(char) < 32 for char in name)
        ):
            raise InvalidInput("Please upload a PDF file with a plain .pdf filename.")
        if upload.content_type not in {"application/pdf", "application/octet-stream"}:
            raise InvalidInput("Please upload a PDF resume.")
        return await asyncio.to_thread(self.extractor.extract, upload.content)
