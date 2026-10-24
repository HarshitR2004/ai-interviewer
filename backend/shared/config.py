from pathlib import Path
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")
    llm_base_url: str
    llm_model: str = Field(min_length=1)
    llm_api_key: SecretStr | None = None
    live_reasoning_timeout_sec: float = Field(default=60, ge=1, le=120)
    data_dir: Path = ROOT / "data"
    live_reasoning_enabled: bool = False
    speech_enabled: bool = False
    stt_base_url: str | None = None
    stt_api_key: SecretStr | None = None
    tts_base_url: str | None = None
    tts_api_key: SecretStr | None = None
    speech_timeout_sec: float = Field(default=60, ge=1, le=180)

    @field_validator("llm_base_url", "stt_base_url", "tts_base_url")
    @classmethod
    def endpoint(cls, value):
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
    def configured(self):
        if not self.llm_base_url or not self.llm_model.strip():
            raise ValueError("Configure LLM_BASE_URL and LLM_MODEL.")
        if self.speech_enabled and not (self.stt_base_url or self.tts_base_url):
            raise ValueError("Configure STT_BASE_URL or TTS_BASE_URL when speech is enabled.")
        if not self.data_dir.is_absolute():
            self.data_dir = ROOT / self.data_dir
        return self
