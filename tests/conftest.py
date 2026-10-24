from io import BytesIO
from pathlib import Path

import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from backend.features.interviews.models import InterviewPlan, Question, RoleRequirements, Section
from backend.features.interviews.service import InterviewService
from backend.features.preparation.service import PreparationService
from backend.features.profiles.models import Persona, Project
from backend.features.profiles.service import ProfileService


def make_service(store, model):
    return PreparationService(store, ProfileService(model), InterviewService(model))


@pytest.fixture
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


@pytest.fixture
def persona():
    return Persona(
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


@pytest.fixture
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


class FakeModel:
    def __init__(self, persona, plan):
        self.persona, self.plan = persona, plan
        self.calls = []
        self.fail_plan = False

    async def generate(self, instruction, content, schema, check=None):
        self.calls.append(schema)
        if schema is Persona:
            result = self.persona.model_copy(deep=True)
            if check:
                check(result)
            return result
        if self.fail_plan:
            raise RuntimeError("generation failed")
        if schema is RoleRequirements:
            return RoleRequirements(
                role=self.plan.role, competencies=self.plan.required_competencies
            )
        section_type = schema.model_fields["sections"].annotation
        from typing import get_args

        sections = {}
        for index, (key, field) in enumerate(section_type.model_fields.items()):
            section = self.plan.sections[index % len(self.plan.sections)].model_dump()
            section["competency"] = get_args(
                field.annotation.model_fields["competency"].annotation
            )[0]
            sections[key] = section
        result = schema.model_validate({"role": self.plan.role, "sections": sections})
        if check:
            check(result)
        return result
