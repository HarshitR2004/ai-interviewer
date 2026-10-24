from io import BytesIO
from pathlib import Path

from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from backend.modules.pre_interview.interview_planning.models import InterviewPlan, Question, Section
from backend.modules.pre_interview.profiles.models import CandidateProfile, Project


def resume_pdf():
    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})}
    )
    stream = DecodedStreamObject()
    text = (Path(__file__).resolve().parents[1] / "sample_data/resume.txt").read_text()
    text = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    lines = text.splitlines()
    commands = " ".join(f"({line}) Tj 0 -16 Td" for line in lines)
    stream.set_data(f"BT /F1 12 Tf 50 700 Td {commands} ET".encode("ascii"))
    page[NameObject("/Contents")] = writer._add_object(stream)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def candidate_profile():
    return CandidateProfile(
        name="Example Candidate",
        background="Python developer",
        education=[],
        experience=[],
        skills={"Languages": ["Python"]},
        projects=[
            Project(
                id="p1",
                name="Booking API",
                purpose="Book slots",
                technologies=["Python"],
                contributions=["Built the API"],
                technical_details=["PostgreSQL"],
                source_refs=["resume"],
            )
        ],
        discussion_topics=["Concurrency"],
        source_references=["resume"],
        collection_status={},
    )


def plan():
    return InterviewPlan(
        role="Software engineer",
        required_competencies=["API design", "Testing"],
        sections=[
            Section(
                title=title,
                competency=title,
                minutes=minutes,
                questions=[
                    Question(
                        question=question,
                        candidate_context="Booking API",
                        project_id="p1",
                        follow_ups=["What changes under concurrent requests?"],
                        strong_answer_signals=["Explains tradeoffs"],
                        scoring_guidance={
                            "weak": "Unsupported guess with no reasoning.",
                            "adequate": "A working approach with basic reasoning.",
                            "strong": "Justified tradeoffs with failure handling.",
                        },
                    )
                ],
            )
            for title, minutes, question in [
                ("API design", 25, "How would you prevent duplicate bookings?"),
                ("Testing", 20, "How would you test booking failures?"),
            ]
        ],
    )


def wav_bytes():
    import io
    import wave

    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(16000)
        writer.writeframes(b"\x00\x00" * 1600)
    return buffer.getvalue()


def preparation(profile=None, interview=None, candidate_id="a" * 32):
    from backend.modules.pre_interview.interview_planning.models import InterviewSettings
    from backend.modules.pre_interview.preparation.models import Preparation

    return Preparation(
        candidate_id=candidate_id,
        profile=profile or candidate_profile(),
        plan=interview or plan(),
        settings=InterviewSettings(),
        job_description="Build Python APIs with database design and testing.",
    )
