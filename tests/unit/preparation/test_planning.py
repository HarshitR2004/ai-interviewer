import pytest
from pydantic import ValidationError

from backend.modules.pre_interview.preparation.blueprint import interview_flow
from backend.modules.pre_interview.preparation.documents import parse_plan, render_plan
from backend.modules.pre_interview.preparation.models import InterviewPlan, InterviewSettings
from backend.modules.pre_interview.preparation.planning import (
    InterviewPlanner,
    allocate_time,
    explicit_competencies,
    planning_schema,
)
from backend.modules.pre_interview.preparation.validation import validate_plan
from tests.fakes import FakeModel


@pytest.mark.parametrize("problem", ["duration", "coverage", "reference", "duplicate"])
def test_invalid_plan_rejected(persona, plan, problem):
    if problem == "duration":
        plan.sections[0].minutes = 1
    elif problem == "coverage":
        plan.required_competencies.append("System design")
    elif problem == "reference":
        plan.sections[0].questions[0].project_id = "missing"
    elif problem == "duplicate":
        plan.sections[1].questions[0].question = plan.sections[0].questions[0].question
    with pytest.raises(ValueError):
        validate_plan(plan, persona, InterviewSettings())


@pytest.mark.parametrize("duration", [15, 45, 120])
def test_model_timing_is_fitted_to_requested_duration(persona, plan, duration):
    plan.sections[0].minutes = 11
    plan.sections[1].minutes = 27
    settings = InterviewSettings(duration=duration)
    allocate_time(plan, settings)
    validate_plan(plan, persona, settings)
    assert sum(section.minutes for section in plan.sections) == duration
    assert all(section.minutes >= 1 for section in plan.sections)


def test_all_three_scoring_anchors_are_required(plan):
    payload = plan.model_dump()
    del payload["sections"][0]["questions"][0]["scoring_guidance"]["adequate"]
    with pytest.raises(ValidationError):
        InterviewPlan.model_validate(payload)


async def test_required_conversation_sections_cannot_be_omitted_or_renamed(persona, plan):
    names = explicit_competencies(
        "Required competencies: Python fundamentals, relational database design."
    )
    assert names == ["Python fundamentals", "relational database design"]
    schema = planning_schema(names)
    plan.required_competencies = names
    payload = (await FakeModel(persona, plan).generate("", {}, schema)).model_dump()
    schema.model_validate(payload)
    valid = (await FakeModel(persona, plan).generate("", {}, schema)).model_dump()
    del payload["sections"]["section_2"]
    with pytest.raises(ValidationError):
        schema.model_validate(payload)
    valid["sections"]["section_1"]["competency"] = "Unrelated topic"
    with pytest.raises(ValidationError):
        schema.model_validate(valid)


@pytest.mark.parametrize("duration", [15, 30, 45, 120])
@pytest.mark.parametrize("has_projects", [True, False])
async def test_conversational_mix_coverage_pacing_and_storage(
    persona, plan, duration, has_projects
):
    if not has_projects:
        persona.projects = []
        for section in plan.sections:
            section.questions[0].project_id = None
    settings = InterviewSettings(duration=duration)
    generated = await InterviewPlanner(FakeModel(persona, plan)).create(
        persona, "Build Python APIs with testing and database design.", settings
    )
    assert generated.format_version == 2
    assert [section.kind for section in generated.sections] == interview_flow(
        settings, has_projects
    )
    assert sum(section.minutes for section in generated.sections) == duration
    assert all(section.minutes >= 1 for section in generated.sections)
    assert generated.sections[0].minutes <= 2
    assert generated.sections[-1].minutes <= 2
    assert not generated.sections[0].scored and not generated.sections[-1].scored
    for section in generated.sections:
        if not section.scored:
            assert section.questions[0].scoring_guidance is None
            assert section.covered_competencies == []
    if has_projects:
        kinds = [section.kind for section in generated.sections]
        assert kinds.index("project_overview") < kinds.index("project_detail")
    else:
        assert all(s.questions[0].project_id is None for s in generated.sections)
    assert parse_plan(render_plan(generated, settings, "job description"), persona)[0] == generated


@pytest.mark.parametrize(
    "problem",
    [
        "opening_score",
        "missing_framework",
        "overloaded",
        "fabricated_project",
        "coverage",
        "unknown_coverage",
        "missing_rubric",
        "too_many_probes",
        "incoherent_project",
    ],
)
async def test_new_plan_rejects_rigid_or_ungrounded_questions(persona, plan, problem):
    generated = await InterviewPlanner(FakeModel(persona, plan)).create(
        persona, "Build Python APIs with testing and database design.", InterviewSettings()
    )
    if problem == "opening_score":
        generated.sections[0].questions[0].scoring_guidance = (
            plan.sections[0].questions[0].scoring_guidance
        )
    elif problem == "missing_framework":
        generated.sections[3].kind = "fundamentals"
    elif problem == "overloaded":
        generated.sections[2].questions[0].question = "Explain Python? Explain SQL?"
    elif problem == "fabricated_project":
        generated.sections[4].questions[0].project_id = "invented"
    elif problem == "coverage":
        generated.required_competencies.append("Uncovered skill")
    elif problem == "unknown_coverage":
        generated.sections[2].covered_competencies.append("Not in the role")
    elif problem == "missing_rubric":
        generated.sections[2].questions[0].scoring_guidance = None
    elif problem == "too_many_probes":
        generated.sections[2].questions[0].follow_ups = ["Why?", "How?", "What happened?"]
    elif problem == "incoherent_project":
        persona.projects.append(persona.projects[0].model_copy(update={"id": "second-project"}))
        generated.sections[4].questions[0].project_id = "second-project"
    with pytest.raises(ValueError):
        validate_plan(generated, persona, InterviewSettings())
