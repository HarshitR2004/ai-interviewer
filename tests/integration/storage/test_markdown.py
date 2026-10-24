import pytest

from backend.common.errors import NotFound, Unavailable
from backend.features.preparation.models import PreparationInputs
from backend.features.preparation.storage import MarkdownPreparationStore
from backend.features.resume_ingestion.service import ResumeUpload
from tests.factories import preparation
from tests.fakes import FakeModel, make_preparation

JD = "Build Python APIs with database design and testing."


async def test_prepare_reload_replan_and_keep_legacy_data(tmp_path, persona, plan, resume_pdf):
    legacy = tmp_path / "v2/keep.json"
    legacy.parent.mkdir()
    legacy.write_bytes(b"existing local data")
    store = MarkdownPreparationStore(tmp_path / "demo/candidates")
    model = FakeModel(persona, plan)
    service = make_preparation(store, model)
    first = await service.submit(
        ResumeUpload("resume.pdf", "application/pdf", resume_pdf),
        PreparationInputs(job_description=JD),
    )
    directory = store.root / first.candidate_id
    assert {p.name for p in directory.iterdir()} == {
        "resume.pdf",
        "persona.md",
        "interview-plan.md",
    }
    assert not list(store.root.rglob("*.json"))
    reloaded_store = MarkdownPreparationStore(store.root)
    assert await reloaded_store.load(first.candidate_id) == first
    profile_before = (directory / "persona.md").read_bytes()
    result = await service.replan(
        first.candidate_id,
        PreparationInputs(job_description=JD + " Updated.", settings={"duration": 30}),
    )
    assert result.settings.duration == 30
    assert await reloaded_store.load(first.candidate_id) == result
    assert (directory / "persona.md").read_bytes() == profile_before
    assert model.calls.count(type(persona)) == 1
    model.fail_plan = True
    previous = (directory / "interview-plan.md").read_bytes()
    with pytest.raises(RuntimeError):
        await service.replan(first.candidate_id, PreparationInputs(job_description=JD))
    assert (directory / "interview-plan.md").read_bytes() == previous
    assert (await service.get(first.candidate_id)).settings.duration == 30
    assert legacy.read_bytes() == b"existing local data"


async def test_atomic_replacement_failure_keeps_old_document(tmp_path, monkeypatch):
    from backend.features.preparation import storage

    store = MarkdownPreparationStore(tmp_path)
    original = preparation()
    await store.create(original, b"resume")
    replacement = original.model_copy(update={"job_description": "Updated role"})

    def fail(*args):
        raise OSError("disk failure")

    monkeypatch.setattr(storage, "atomic_write", fail)
    with pytest.raises(Unavailable):
        await store.replace_plan(replacement)
    assert await store.load(original.candidate_id) == original


@pytest.mark.parametrize("missing", ["persona.md", "interview-plan.md"])
async def test_incomplete_preparation_cannot_be_loaded(tmp_path, missing):
    store = MarkdownPreparationStore(tmp_path)
    value = preparation()
    await store.create(value, b"resume")
    (tmp_path / value.candidate_id / missing).unlink()
    with pytest.raises(NotFound):
        await store.load(value.candidate_id)
    with pytest.raises(NotFound):
        await store.load("../outside")


async def test_initial_write_failure_is_not_reported_as_completed(tmp_path, monkeypatch):
    from backend.features.preparation import storage

    real = storage.atomic_write

    def fail_plan(path, content):
        if path.name == "interview-plan.md":
            raise OSError("disk full")
        real(path, content)

    monkeypatch.setattr(storage, "atomic_write", fail_plan)
    store = MarkdownPreparationStore(tmp_path)
    value = preparation()
    with pytest.raises(Unavailable):
        await store.create(value, b"resume")
    with pytest.raises(NotFound):
        await store.load(value.candidate_id)
