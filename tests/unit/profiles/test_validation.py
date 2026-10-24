import pytest

from backend.modules.profiles.validation import validate_profile


@pytest.mark.parametrize("problem", ["duplicate_id", "source"])
def test_invalid_profile_references(persona, problem):
    if problem == "duplicate_id":
        persona.projects.append(persona.projects[0].model_copy(deep=True))
    else:
        persona.projects[0].source_refs = ["made-up-source"]
    with pytest.raises(ValueError):
        validate_profile(persona, {"resume"})
