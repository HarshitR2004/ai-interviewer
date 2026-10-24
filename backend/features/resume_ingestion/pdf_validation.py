"""Validate untrusted resume PDFs before persistence or model processing."""

import re
from io import BytesIO
from urllib.parse import urlsplit

from pypdf import PdfReader

from backend.common.errors import InvalidInput

MAX_PDF_BYTES = 10 * 1024 * 1024
MAX_TEXT_CHARS = 24000
PARSER_TIMEOUT_SECONDS = 10
_INVALID = "This PDF could not be safely read. Please upload a plain text-based PDF."
_ACTIVE = "PDF scripts, automatic actions, forms, and embedded files are not accepted."
_BLOCKED_KEYS = {
    "/JavaScript",
    "/JS",
    "/OpenAction",
    "/AA",
    "/AcroForm",
    "/XFA",
    "/EmbeddedFiles",
    "/EmbeddedFile",
    "/EF",
    "/AF",
    "/RichMedia",
    "/RichMediaContent",
    "/Movie",
    "/Sound",
    "/3D",
    "/Collection",
}
_BLOCKED_ACTIONS = {
    "/JavaScript",
    "/Launch",
    "/SubmitForm",
    "/ImportData",
    "/GoToR",
    "/GoToE",
    "/Rendition",
    "/Movie",
    "/Sound",
    "/Hide",
    "/ResetForm",
    "/SetOCGState",
}


def _check_envelope(content: bytes) -> None:
    if not content or len(content) > MAX_PDF_BYTES:
        raise InvalidInput("Please upload a PDF of at most 10 MB.")
    if not re.match(rb"%PDF-(?:1\.[0-7]|2\.0)(?:\r\n|\r|\n)", content):
        raise InvalidInput("Please upload a valid PDF resume.")
    if not content.rstrip(b" \t\r\n").endswith(b"%%EOF"):
        raise InvalidInput(_INVALID)


def _check_objects(reader: PdfReader) -> None:
    from pypdf.generic import ArrayObject, DictionaryObject, IndirectObject

    references = {
        (number, generation)
        for generation, entries in reader.xref.items()
        if generation != 65535
        for number in entries
        if number != 0
    }
    references.update((number, 0) for number in reader.xref_objStm)
    if len(references) > 10000:
        raise InvalidInput("This PDF is too complex to process safely.")
    stack: list[object] = [reader.trailer]
    stack.extend(IndirectObject(number, generation, reader) for number, generation in references)
    seen_refs: set[tuple[int, int]] = set()
    seen_objects: set[int] = set()
    visited = 0
    while stack:
        visited += 1
        if visited > 100000:
            raise InvalidInput("This PDF is too complex to process safely.")
        value = stack.pop()
        if isinstance(value, IndirectObject):
            key = (value.idnum, value.generation)
            if key in seen_refs:
                continue
            seen_refs.add(key)
            value = value.get_object()
        if not isinstance(value, (DictionaryObject, ArrayObject)):
            continue
        if id(value) in seen_objects:
            continue
        seen_objects.add(id(value))
        if isinstance(value, DictionaryObject):
            if _BLOCKED_KEYS.intersection(value):
                raise InvalidInput(_ACTIVE)
            if value.get("/Type") in {"/EmbeddedFile", "/Filespec", "/RichMedia", "/3D"}:
                raise InvalidInput(_ACTIVE)
            action = value.get("/S")
            if action in _BLOCKED_ACTIONS or (
                value.get("/Type") == "/Action" and action not in {"/URI", "/GoTo"}
            ):
                raise InvalidInput(_ACTIVE)
            if "/URI" in value:
                uri = value["/URI"]
                if not isinstance(uri, str) or urlsplit(uri).scheme.lower() not in {
                    "https",
                    "http",
                    "mailto",
                }:
                    raise InvalidInput("This PDF contains an unsupported link action.")
            stack.extend(value.values())
        else:
            stack.extend(value)


def _extract_checked(content: bytes) -> str:
    from pypdf import PdfReader, apply_configuration

    _check_envelope(content)
    try:
        with apply_configuration(
            maximum_declared_stream_length=8 * 1024 * 1024,
            array_based_stream_maximum_output_length=8 * 1024 * 1024,
            zlib_maximum_output_length=8 * 1024 * 1024,
            lzw_maximum_output_length=8 * 1024 * 1024,
            run_length_maximum_output_length=8 * 1024 * 1024,
            stream_decoding_work_maximum_length=16 * 1024 * 1024,
            stream_parsing_work_maximum_count=100000,
            stream_filters_maximum_length=4,
            array_maximum_element_count=10000,
            dictionary_maximum_element_count=10000,
            page_tree_maximum_entries=100,
            page_tree_maximum_depth=10,
            xform_maximum_invocations_per_extraction=100,
        ):
            reader = PdfReader(BytesIO(content), strict=True, root_object_recovery_limit=100)
            if reader.is_encrypted:
                raise InvalidInput("Please upload a PDF without password protection.")
            _check_objects(reader)
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
            text = "\n\n".join(parts).strip()
    except InvalidInput:
        raise
    except Exception:
        raise InvalidInput(_INVALID) from None
    if len(text) < 40:
        raise InvalidInput("This resume has no readable text. Please upload a text-based PDF.")
    return text
