from pathlib import Path
from urllib.parse import urlsplit

from pydantic import AliasChoices, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")
    llm_base_url: str
    llm_model: str = Field(min_length=1)
    llm_api_key: SecretStr | None = Field(
        default=None, validation_alias=AliasChoices("GEMINI_API_KEY", "llm_api_key")
    )
    live_reasoning_timeout_sec: float = Field(default=8, ge=1, le=30)
    data_dir: Path = ROOT / "data"
    livekit_url: str = "ws://127.0.0.1:7880"
    livekit_api_key: str = "devkey"
    livekit_api_secret: SecretStr = SecretStr("secret")
    agent_secret: SecretStr = SecretStr("local-interview-agent-change-me")
    backend_url: str = "http://127.0.0.1:8000"
    gemini_stt_model: str = "gemini-3.5-transcribe-live"
    gemini_tts_model: str = "gemini-3.1-flash-tts-preview"
    gemini_tts_voice: str = "Kore"
    live_llm_model: str | None = None
    min_endpoint_delay: float = Field(default=0, ge=0, le=5)
    max_endpoint_delay: float = Field(default=0, ge=0, le=10)
    interruption_duration: float = Field(default=0.4, ge=0.2, le=2)

    @field_validator("llm_base_url", "backend_url")
    @classmethod
    def endpoint(cls, value: str | None) -> str | None:
        # Normalize provider URLs and reject credentials or request-specific URL components.
        if value is None or not value.strip():
            return None
        try:
            parsed = urlsplit(value)
            valid = (
                parsed.scheme in {"http", "https"}
                and parsed.hostname
                and not parsed.username
                and not parsed.password
                and not parsed.query
                and not parsed.fragment
            )
            _ = parsed.port
        except ValueError:
            valid = False
        if not valid:
            raise ValueError("Use an HTTP(S) base URL without credentials, query, or fragment.")
        return value.rstrip("/")

    @model_validator(mode="after")
    def configured(self) -> "Settings":
        # Check enabled capabilities and resolve storage relative to the project root.
        if not self.llm_base_url or not self.llm_model.strip():
            raise ValueError("Configure LLM_BASE_URL and LLM_MODEL.")
        if self.max_endpoint_delay < self.min_endpoint_delay:
            raise ValueError("Maximum endpoint delay must be at least the minimum delay.")
        if not self.data_dir.is_absolute():
            self.data_dir = ROOT / self.data_dir
        return self
