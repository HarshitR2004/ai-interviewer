import pytest
from pydantic import ValidationError

from backend.features.interviews.models import InterviewPlan, InterviewSettings
from backend.features.interviews.planning import explicit_competencies, planning_schema
from backend.features.interviews.validation import allocate_time, validate_plan


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


def test_required_role_sections_cannot_be_omitted_or_renamed(plan):
    names = explicit_competencies(
        "Required competencies: Python fundamentals, relational database design."
    )
    assert names == ["Python fundamentals", "relational database design"]
    schema = planning_schema(names)
    payload = {"role": "Engineer", "sections": {}}
    for index, name in enumerate(names, start=1):
        section = plan.sections[0].model_dump()
        section["competency"] = name
        payload["sections"][f"section_{index}"] = section
    schema.model_validate(payload)
    del payload["sections"]["section_2"]
    with pytest.raises(ValidationError):
        schema.model_validate(payload)
    payload["sections"]["section_1"]["competency"] = "Unrelated topic"
    with pytest.raises(ValidationError):
        schema.model_validate(payload)
