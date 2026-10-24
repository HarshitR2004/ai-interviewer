import asyncio
from dataclasses import dataclass
from io import BytesIO

from pypdf import PdfReader

from backend.common.errors import InvalidInput

MAX_PDF_BYTES = 10 * 1024 * 1024
MAX_TEXT_CHARS = 24000


@dataclass(frozen=True)
class ResumeUpload:
    filename: str
    content_type: str
    content: bytes


class PdfExtractor:
    async def ingest(self, upload: ResumeUpload) -> str:
        name = upload.filename
        if (
            not name.lower().endswith(".pdf")
            or any(char in name for char in "/\\:")
            or any(ord(char) < 32 for char in name)
        ):
            raise InvalidInput("Please upload a PDF file with a plain .pdf filename.")
        if upload.content_type not in {"application/pdf", "application/octet-stream"}:
            raise InvalidInput("Please upload a PDF resume.")
        return await asyncio.to_thread(self.extract, upload.content)

    def extract(self, content: bytes) -> str:
        # Apply basic PDF checks before extracting text for the profile generator.
        if not content or len(content) > MAX_PDF_BYTES:
            raise InvalidInput("Please upload a PDF of at most 10 MB.")
        if not content.startswith(b"%PDF-"):
            raise InvalidInput("Please upload a valid PDF resume.")
        try:
            reader = PdfReader(BytesIO(content))
            if reader.is_encrypted:
                raise InvalidInput("Please upload a PDF without password protection.")
            if not 1 <= len(reader.pages) <= 20:
                raise InvalidInput("Please use a resume with 1 to 20 pages.")
            parts: list[str] = []
            length = 0
            for page in reader.pages:
                text = page.extract_text() or ""
                length += len(text) + (2 if parts else 0)
                if length > MAX_TEXT_CHARS:
                    raise InvalidInput("This resume is too long. Please upload a shorter version.")
                parts.append(text)
        except InvalidInput:
            raise
        except Exception as exc:
            raise InvalidInput("This PDF could not be read. Please upload a valid PDF resume.") from exc
        text = "\n\n".join(parts).strip()
        if len(text) < 40:
            raise InvalidInput("This resume has no readable text. Please upload a text-based PDF.")
        return text
