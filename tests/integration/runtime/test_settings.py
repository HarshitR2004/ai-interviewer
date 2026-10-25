import pytest
from pydantic import ValidationError

from backend.settings import Settings


def config(**kwargs):
    return Settings(
        _env_file=None, llm_base_url="https://llm.example/v1", llm_model="model", **kwargs
    )


def test_required_llm_configuration(monkeypatch):
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_gemini_key_configuration(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "private-google-key")
    monkeypatch.setenv("LLM_API_KEY", "obsolete-key")
    settings = config()
    assert settings.llm_api_key.get_secret_value() == "private-google-key"
    assert "private-google-key" not in repr(settings)


@pytest.mark.parametrize(
    "url",
    [
        "file:///tmp/service",
        "https://user:password@example.com",
        "https://example.com?key=secret",
        "https://example.com/#part",
        "https://example.com:wrong",
        "missing-scheme",
    ],
)
def test_invalid_endpoints(url):
    with pytest.raises(ValidationError):
        config(backend_url=url)


def test_voice_defaults_and_secret_values():
    settings = config(agent_secret="private-value")
    assert settings.live_reasoning_timeout_sec == 8
    assert settings.min_endpoint_delay == 0
    assert "private-value" not in repr(settings)
    with pytest.raises(ValidationError):
        config(min_endpoint_delay=4, max_endpoint_delay=3)
