import pytest

from backend.features.profiles.validation import validate_persona


@pytest.mark.parametrize("problem", ["duplicate_id", "source"])
def test_invalid_profile_references(persona, problem):
    if problem == "duplicate_id":
        persona.projects.append(persona.projects[0].model_copy(deep=True))
    else:
        persona.projects[0].source_refs = ["made-up-source"]
    with pytest.raises(ValueError):
        validate_persona(persona, {"resume"})
