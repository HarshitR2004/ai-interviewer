import pytest
from conftest import FakeModel, make_service

from backend.features.interviews.models import InterviewSettings
from backend.features.preparation.storage import LocalStore
from backend.features.profiles.models import Persona


async def test_success_and_replan(tmp_path, persona, plan):
    store = LocalStore(tmp_path)
    model = FakeModel(persona, plan)
    service = make_service(store, model)
    first = store.create()
    await service.prepare(first, "resume", "job description", InterviewSettings())
    path = store.candidate(first)
    assert store.status(first).state == "completed"
    assert not (path / "sources").exists()
    assert not (tmp_path / ".cache").exists()
    for name in (
        "persona.md",
        "interview.md",
        "structured/persona.json",
        "structured/interview.json",
        "inputs/settings.json",
        "inputs/job_description.txt",
    ):
        assert (path / name).is_file()
    second = store.create()
    await service.prepare(second, "resume", "job description", InterviewSettings())
    before = (path / "persona.md").read_bytes()
    await service.replan(first, "Updated job description", InterviewSettings())
    assert model.calls.count(Persona) == 2
    assert (path / "persona.md").read_bytes() == before
    assert (path / "inputs/job_description.txt").read_text() == "Updated job description"


async def test_failed_replan_preserves_previous_outputs(tmp_path, persona, plan):
    store = LocalStore(tmp_path)
    model = FakeModel(persona, plan)
    service = make_service(store, model)
    candidate = store.create()
    await service.prepare(candidate, "resume", "original job", InterviewSettings())
    path = store.candidate(candidate)
    before = {
        name: (path / name).read_bytes()
        for name in (
            "persona.md",
            "interview.md",
            "structured/interview.json",
            "inputs/job_description.txt",
        )
    }
    model.fail_plan = True
    await service.replan(candidate, "replacement job", InterviewSettings())
    assert store.status(candidate).state == "failed"
    assert before == {name: (path / name).read_bytes() for name in before}


def test_restart_recovery_and_candidate_path(tmp_path):
    store = LocalStore(tmp_path)
    candidate = store.create()
    store.recover()
    assert store.status(candidate).state == "failed"
    with pytest.raises(FileNotFoundError):
        store.candidate("../outside")
