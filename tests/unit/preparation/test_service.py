import asyncio

import pytest

from backend.common.errors import Conflict
from backend.modules.pre_interview.preparation.models import PreparationInputs
from tests.factories import preparation
from tests.fakes import FakeModel, make_preparation


async def test_replan_guard_and_cancellation_use_only_store_port(persona, plan):
    class Store:
        value = preparation()

        async def load(self, candidate_id):
            return self.value.model_copy(deep=True)

        async def replace_plan(self, value):
            self.value = value

    class PendingModel(FakeModel):
        started = asyncio.Event()
        release = asyncio.Event()

        async def generate(self, *args, **kwargs):
            self.started.set()
            await self.release.wait()
            return await super().generate(*args, **kwargs)

    store = Store()
    model = PendingModel(persona, plan)
    service = make_preparation(store, model)
    body = PreparationInputs(job_description="Build Python APIs with database design and testing.")
    pending = asyncio.create_task(service.replan(store.value.candidate_id, body))
    await model.started.wait()
    with pytest.raises(Conflict):
        await service.replan(store.value.candidate_id, body)
    with pytest.raises(Conflict):
        await service.get(store.value.candidate_id)
    before = store.value.model_copy(deep=True)
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending
    assert await service.get(store.value.candidate_id) == before
    model.release.set()
    assert (await service.replan(store.value.candidate_id, body)).profile == before.profile
