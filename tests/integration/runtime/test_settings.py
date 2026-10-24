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
        config(stt_base_url=url)


def test_independent_speech_endpoints_and_secret_values():
    settings = config(
        speech_enabled=True, stt_base_url="https://stt.example/api/", stt_api_key="private-stt-key"
    )
    assert settings.stt_base_url == "https://stt.example/api"
    assert settings.tts_base_url is None
    assert "private-stt-key" not in repr(settings)
    with pytest.raises(ValidationError):
        config(speech_enabled=True)
