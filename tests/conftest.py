import pytest

from tests.factories import candidate_profile
from tests.factories import plan as make_plan
from tests.factories import resume_pdf as make_resume_pdf


@pytest.fixture
def persona():
    return candidate_profile()


@pytest.fixture
def plan():
    return make_plan()


@pytest.fixture
def resume_pdf():
    return make_resume_pdf()


@pytest.fixture(autouse=True)
def offline_network(monkeypatch):
    import httpx

    async def blocked(*args, **kwargs):
        raise AssertionError("Real HTTP requests are disabled in tests; inject MockTransport")

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", blocked)
