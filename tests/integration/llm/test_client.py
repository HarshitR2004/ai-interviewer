import httpx
import pytest

from backend.common.errors import Unavailable
from backend.integrations.llm.client import ChatCompletionsClient
from backend.integrations.llm.structured_generation import StructuredGeneration
from backend.modules.pre_interview.profiles.models import CandidateProfile


async def test_model_repairs_once(monkeypatch, persona):
    calls = []

    async def post(self, url, **kwargs):
        calls.append(kwargs["json"])
        content = "{}" if len(calls) == 1 else persona.model_dump_json()
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": content}, "finish_reason": "stop"}]},
            request=httpx.Request("POST", "https://llm.example/v1/chat/completions"),
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", post)
    client = ChatCompletionsClient("https://llm.example/v1", "test-model", "test-key")
    result = await StructuredGeneration(client).generate("test", {}, CandidateProfile)
    assert result.name == persona.name
    assert len(calls) == 2
    assert all(call["model"] == "test-model" for call in calls)
    assert all(call["response_format"] == {"type": "json_object"} for call in calls)
    assert all("provider" not in call and "reasoning" not in call for call in calls)


async def test_model_stops_after_failed_repair(monkeypatch):
    calls = []

    async def post(self, url, **kwargs):
        calls.append(url)
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}]},
            request=httpx.Request("POST", "https://llm.example/v1/chat/completions"),
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", post)
    with pytest.raises(Unavailable):
        await StructuredGeneration(
            ChatCompletionsClient("https://llm.example/v1", "test-model", "test-key")
        ).generate("test", {}, CandidateProfile)
    assert len(calls) == 2


async def test_http_failure_is_redacted_and_not_retried(caplog):
    calls = []

    def handler(request):
        calls.append(request)
        assert request.headers["authorization"] == "Bearer secret-test-key"
        return httpx.Response(401, json={"error": {"message": "secret-test-key"}})

    client = ChatCompletionsClient(
        "https://llm.example/v1",
        "test-model",
        "secret-test-key",
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(Unavailable) as error:
        await StructuredGeneration(client).generate("test", {}, CandidateProfile)
    assert len(calls) == 1
    assert "secret-test-key" not in str(error.value) + caplog.text


async def test_truncated_output_does_not_trigger_repair():
    def handler(request):
        return httpx.Response(
            200, json={"choices": [{"message": {"content": "{}"}, "finish_reason": "length"}]}
        )

    with pytest.raises(Unavailable):
        await StructuredGeneration(
            ChatCompletionsClient(
                "https://llm.example/v1",
                "test-model",
                "test-key",
                transport=httpx.MockTransport(handler),
            )
        ).generate("test", {}, CandidateProfile)


@pytest.mark.parametrize("key", [None, "optional-key"])
async def test_configurable_endpoint_and_optional_auth(key):
    def handler(request):
        import json

        assert str(request.url) == "http://localhost:9000/custom/v1/chat/completions"
        assert request.headers.get("authorization") == (f"Bearer {key}" if key else None)
        body = json.loads(request.content)
        assert body["model"] == "my-own-model"
        assert "provider" not in body and "reasoning" not in body
        assert "x-openrouter-title" not in request.headers
        # Providers may canonicalize the model name in the response.
        return httpx.Response(
            200,
            json={
                "model": "canonical-model",
                "choices": [{"message": {"content": '{"ok":true}'}, "finish_reason": "stop"}],
            },
        )

    client = ChatCompletionsClient(
        "http://localhost:9000/custom/v1",
        "my-own-model",
        key,
        transport=httpx.MockTransport(handler),
    )
    assert await client.complete([]) == '{"ok":true}'


@pytest.mark.parametrize(
    "body",
    [
        [],
        {},
        {"choices": []},
        {"choices": [None]},
        {"choices": [{"message": {"content": None}}]},
        {"error": {"message": "private-provider-body"}},
    ],
)
async def test_malformed_provider_envelopes_are_sanitized(body, caplog):
    client = ChatCompletionsClient(
        "https://llm.example/v1",
        "test-model",
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=body)),
    )
    with pytest.raises(Unavailable) as error:
        await client.complete([])
    assert "private-provider-body" not in str(error.value) + caplog.text


async def test_timeout_is_sanitized_and_not_retried():
    calls = []

    def handler(request):
        calls.append(request)
        assert request.extensions["timeout"]["read"] == 3
        raise httpx.ReadTimeout("private-timeout-details", request=request)

    client = ChatCompletionsClient(
        "https://llm.example/v1", "test-model", transport=httpx.MockTransport(handler)
    )
    with pytest.raises(Unavailable, match="temporarily unavailable") as error:
        await client.complete([], timeout=3)
    assert len(calls) == 1 and "private-timeout-details" not in str(error.value)
