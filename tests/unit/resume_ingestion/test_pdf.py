from io import BytesIO

import pytest
from pypdf import PdfWriter

from backend.common.errors import InvalidInput
from backend.modules.resume_ingestion.pdf_extractor import extract_resume


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


def test_https_project_links_remain_allowed(resume_pdf):
    from pypdf.annotations import Link

    payload = modified_pdf(
        resume_pdf,
        lambda writer: writer.add_annotation(
            page_number=0,
            annotation=Link(rect=(0, 0, 100, 20), url="https://github.com/example/project"),
        ),
    )
    assert "Booking API" in extract_resume(payload)


def test_rejects_encrypted_and_excessive_page_pdfs(resume_pdf):
    with pytest.raises(InvalidInput, match="password"):
        extract_resume(
            modified_pdf(resume_pdf, lambda writer: writer.encrypt("synthetic-password"))
        )

    def many_pages(writer):
        for _ in range(20):
            writer.add_blank_page(612, 792)

    with pytest.raises(InvalidInput, match="20 pages"):
        extract_resume(modified_pdf(resume_pdf, many_pages))


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


def test_rejects_excessive_text(resume_pdf):
    from pypdf.generic import DecodedStreamObject, NameObject

    def long_text(writer):
        stream = DecodedStreamObject()
        stream.set_data(b"BT /F1 10 Tf (" + b"a" * 24001 + b") Tj ET")
        writer.pages[0][NameObject("/Contents")] = writer._add_object(stream)

    with pytest.raises(InvalidInput, match="too long"):
        extract_resume(modified_pdf(resume_pdf, long_text))
