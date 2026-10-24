import pytest

from backend.common.markdown import DocumentFormatError
from backend.modules.interview_planning.models import InterviewSettings
from backend.modules.preparation.documents import (
    parse_plan,
    parse_profile,
    render_plan,
    render_profile,
)
from tests.factories import preparation


def test_full_round_trip(persona, plan):
    value = preparation(persona, plan)
    assert parse_profile(render_profile(persona)) == persona
    restored, settings, jd = parse_plan(
        render_plan(plan, value.settings, value.job_description), persona
    )
    assert restored == plan and settings == value.settings and jd == value.job_description


@pytest.mark.parametrize("legacy_type", ["mixed", "technical", "project"])
def test_legacy_interview_type_is_discarded(persona, plan, legacy_type):
    document = render_plan(plan, InterviewSettings(), "job description")
    assert "Interview Type" not in document
    document = document.replace(
        "## Job Description",
        f"### Interview Type\n\n> {legacy_type}\n\n## Job Description",
    )
    restored, settings, _ = parse_plan(document, persona)
    assert restored == plan
    assert settings.model_dump() == {"duration": 45, "seniority": "junior"}


@pytest.mark.parametrize(
    "text",
    [
        "",
        "雪 café **bold** | `code`",
        "# Heading\n\n> quoted\n- bullet\n```python\npass\n```\n",
        "  spaced  ",
        "Not project-specific.",
        "No entries.",
    ],
)
def test_text_and_list_values_are_lossless(persona, plan, text):
    persona.name = text
    persona.background = text
    persona.education = [text, "second\n\n  continuation\n"]
    persona.skills = {text: [text]}
    persona.projects[0].purpose = text
    persona.collection_status = {text: text}
    assert parse_profile(render_profile(persona)) == persona
    plan.sections[0].questions[0].candidate_context = text
    parsed, _, jd = parse_plan(render_plan(plan, InterviewSettings(), text), persona)
    assert parsed == plan and jd == text


def test_empty_groups_and_null_reference(persona, plan):
    persona.projects, persona.skills, persona.collection_status = [], {}, {}
    for section in plan.sections:
        section.questions[0].project_id = None
    assert parse_profile(render_profile(persona)) == persona
    document = render_plan(plan, InterviewSettings(), "")
    assert "Not project-specific." in document
    assert parse_plan(document, persona)[0] == plan


@pytest.mark.parametrize(
    "change",
    [
        lambda s: s.replace("## Identity", "## Missing Identity"),
        lambda s: s.replace("## Background", "## Identity\n\n## Background"),
        lambda s: s.replace("### Project 1", "### Project 2"),
        lambda s: s + "## Unknown\n",
        lambda s: s.replace("> Example Candidate", "Example Candidate"),
        lambda s: s.replace(
            "#### Category\n\n> Languages",
            "#### Category\n\n> Languages\n\n### Skill Group 1\n\n#### Category\n\n> Other\n\n#### Skills\n\n- x",
        ),
    ],
)
def test_bad_profile_documents_are_rejected(persona, change):
    with pytest.raises(DocumentFormatError):
        parse_profile(change(render_profile(persona)))


@pytest.mark.parametrize(
    "change",
    [
        lambda s: s.replace("> 45", "> not-a-number", 1),
        lambda s: s.replace("> 45", "> 999", 1),
        lambda s: s.replace("> 25", "> 24", 1),
        lambda s: s.replace("> p1", "> missing-project"),
        lambda s: s.replace("#### Competency", "#### Unknown Competency", 1),
        lambda s: s.replace("### Section 2", "### Section 1"),
        lambda s: s.replace("##### Strong", "##### Adequate", 1),
    ],
)
def test_bad_plan_documents_are_rejected(persona, plan, change):
    with pytest.raises(DocumentFormatError):
        parse_plan(change(render_plan(plan, InterviewSettings(), "job description")), persona)


def test_crlf_document_line_endings_are_supported(persona):
    assert parse_profile(render_profile(persona).replace("\n", "\r\n")) == persona
