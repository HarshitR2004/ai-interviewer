from io import BytesIO

import pytest
from pypdf import PdfWriter

from backend.common.errors import InvalidInput
from backend.features.resume_ingestion.pdf_extractor import extract_resume


def test_pdf_extraction(resume_pdf):
    assert "Python backend developer" in extract_resume(resume_pdf)


def test_scanned_and_invalid_pdfs():
    writer = PdfWriter()
    writer.add_blank_page(612, 792)
    output = BytesIO()
    writer.write(output)
    for payload in (b"bad content", output.getvalue()):
        with pytest.raises(InvalidInput):
            extract_resume(payload)


def modified_pdf(resume_pdf, change):
    from pypdf import PdfReader

    writer = PdfWriter()
    writer.clone_document_from_reader(PdfReader(BytesIO(resume_pdf)))
    change(writer)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


@pytest.mark.parametrize(
    "kind",
    [
        "javascript",
        "open_action",
        "additional_action",
        "attachment",
        "form",
        "launch",
        "unsafe_uri",
        "unused_script",
    ],
)
def test_rejects_active_pdf_content(resume_pdf, kind):
    from pypdf.generic import DictionaryObject, NameObject, TextStringObject

    from backend.features.resume_ingestion.pdf_validation import _extract_checked

    def change(writer):
        script = DictionaryObject(
            {
                NameObject("/S"): NameObject("/JavaScript"),
                NameObject("/JS"): TextStringObject("app.alert('synthetic')"),
            }
        )
        if kind == "javascript":
            writer.add_js("app.alert('synthetic')")
        elif kind == "open_action":
            writer.root_object[NameObject("/OpenAction")] = script
        elif kind == "additional_action":
            writer.pages[0][NameObject("/AA")] = DictionaryObject({NameObject("/O"): script})
        elif kind == "attachment":
            writer.add_attachment("synthetic.txt", b"synthetic attachment")
        elif kind == "form":
            writer.root_object[NameObject("/AcroForm")] = DictionaryObject()
        elif kind == "launch":
            writer.root_object[NameObject("/A")] = DictionaryObject(
                {
                    NameObject("/S"): NameObject("/Launch"),
                    NameObject("/F"): TextStringObject("example.exe"),
                }
            )
        elif kind == "unsafe_uri":
            writer.root_object[NameObject("/A")] = DictionaryObject(
                {
                    NameObject("/S"): NameObject("/URI"),
                    NameObject("/URI"): TextStringObject("file:///private"),
                }
            )
        else:
            writer._add_object(script)

    with pytest.raises(InvalidInput):
        _extract_checked(modified_pdf(resume_pdf, change))


def test_https_project_links_remain_allowed(resume_pdf):
    from pypdf.annotations import Link

    from backend.features.resume_ingestion.pdf_validation import _extract_checked

    payload = modified_pdf(
        resume_pdf,
        lambda writer: writer.add_annotation(
            page_number=0,
            annotation=Link(rect=(0, 0, 100, 20), url="https://github.com/example/project"),
        ),
    )
    assert "Booking API" in _extract_checked(payload)


def test_rejects_encrypted_and_excessive_page_pdfs(resume_pdf):
    from backend.features.resume_ingestion.pdf_validation import _extract_checked

    with pytest.raises(InvalidInput, match="password"):
        _extract_checked(
            modified_pdf(resume_pdf, lambda writer: writer.encrypt("synthetic-password"))
        )

    def many_pages(writer):
        for _ in range(20):
            writer.add_blank_page(612, 792)

    with pytest.raises(InvalidInput, match="20 pages"):
        _extract_checked(modified_pdf(resume_pdf, many_pages))


def test_rejects_decompression_bomb(resume_pdf):
    from pypdf.generic import DecodedStreamObject, NameObject

    from backend.features.resume_ingestion.pdf_validation import _extract_checked

    def oversized_stream(writer):
        stream = DecodedStreamObject()
        stream.set_data(b" " * (9 * 1024 * 1024))
        writer.pages[0][NameObject("/Contents")] = writer._add_object(stream.flate_encode())

    with pytest.raises(InvalidInput):
        _extract_checked(modified_pdf(resume_pdf, oversized_stream))


@pytest.mark.parametrize(
    "payload",
    [
        b"%PDF-1.7\nnot a PDF\n%%EOF",
        b"%PDF-1.7\n" + b"x" * (10 * 1024 * 1024),
        b"MZ executable",
        b"PK archive",
    ],
    ids=["malformed-pdf", "oversized", "executable", "archive"],
)
def test_rejects_spoofed_or_oversized_files(payload):
    with pytest.raises(InvalidInput):
        extract_resume(payload)


def test_rejects_trailing_payload_and_truncated_pdf(resume_pdf):
    for payload in (resume_pdf + b"PK appended archive", resume_pdf[:-12]):
        with pytest.raises(InvalidInput):
            extract_resume(payload)


def test_worker_timeout_and_secret_isolation(monkeypatch, resume_pdf):
    import subprocess

    from backend.features.resume_ingestion import pdf_extractor as resume

    def timeout(*args, **kwargs):
        assert kwargs["timeout"] == resume.PARSER_TIMEOUT_SECONDS
        assert "LLM_API_KEY" not in kwargs["env"]
        assert "PYTHONPATH" not in kwargs["env"]
        raise subprocess.TimeoutExpired(args[0], kwargs["timeout"])

    monkeypatch.setenv("LLM_API_KEY", "synthetic-secret")
    monkeypatch.setenv("PYTHONPATH", "synthetic-untrusted-path")
    monkeypatch.setattr(resume.subprocess, "run", timeout)
    with pytest.raises(InvalidInput, match="too long"):
        extract_resume(resume_pdf)


def test_parser_concurrency_is_bounded(monkeypatch, resume_pdf):
    from backend.features.resume_ingestion import pdf_extractor as resume

    class Busy:
        def acquire(self, blocking):
            assert blocking is False
            return False

    monkeypatch.setattr(resume, "_PARSER_SLOTS", Busy())
    with pytest.raises(InvalidInput, match="busy"):
        extract_resume(resume_pdf)
