from typing import Any

import httpx
from pydantic import SecretStr

from backend.common.errors import InvalidInput, Unavailable

from .contracts import Transcript
from .wav import MAX_AUDIO_BYTES, validate_wav


class SpeechClient:
    def __init__(
        self,
        stt_base_url: str | None = None,
        tts_base_url: str | None = None,
        *,
        stt_api_key: SecretStr | str | None = None,
        tts_api_key: SecretStr | str | None = None,
        timeout: float = 60,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:

        self.stt_url, self.tts_url = stt_base_url, tts_base_url

        self.stt_key, self.tts_key = stt_api_key, tts_api_key

        self.timeout, self.transport = timeout, transport
        self._client = httpx.AsyncClient(transport=transport, trust_env=False)

    async def call(
        self, url: str | None, path: str, key: SecretStr | str | None, **kwargs: Any
    ) -> bytes:

        if not url:
            raise Unavailable("The requested speech endpoint is not configured.")

        secret = key.get_secret_value() if isinstance(key, SecretStr) else key

        headers = {"Authorization": f"Bearer {secret}"} if secret else {}

        try:
            # Bound response size before buffering audio or provider error bodies.

            async with self._client.stream(
                "POST",
                url.rstrip("/") + "/" + path,
                headers=headers,
                timeout=httpx.Timeout(self.timeout, connect=min(10, self.timeout)),
                **kwargs,
            ) as response:
                if response.status_code == 422:
                    raise InvalidInput("The speech provider rejected the input.")

                response.raise_for_status()

                parts, size = [], 0

                async for chunk in response.aiter_bytes():
                    size += len(chunk)

                    if size > MAX_AUDIO_BYTES:
                        raise Unavailable("The speech provider response exceeded the size limit.")

                    parts.append(chunk)

                return b"".join(parts)

        except httpx.HTTPError as exc:
            raise Unavailable("The speech provider is temporarily unavailable.") from exc

    async def transcribe(self, content: bytes) -> Transcript:

        validate_wav(content)

        raw = await self.call(
            self.stt_url,
            "transcribe",
            self.stt_key,
            files={"audio": ("answer.wav", content, "audio/wav")},
        )

        try:
            import json

            value = json.loads(raw)

            text = value["text"]

            if not isinstance(text, str):
                raise ValueError

        except (ValueError, KeyError, TypeError, UnicodeDecodeError) as exc:
            raise Unavailable("The STT provider returned an invalid transcript.") from exc

        if not text.strip():
            raise InvalidInput("No speech was recognized. Record your answer again.")

        if len(text) > 16000:
            raise InvalidInput("Recognized answer is too long.")

        return Transcript(text=text.strip())

    async def synthesize(self, text: str) -> bytes:

        content = await self.call(self.tts_url, "synthesize", self.tts_key, json={"text": text})

        try:
            validate_wav(content)

        except InvalidInput as exc:
            raise Unavailable("The TTS provider returned invalid WAV audio.") from exc

        return content

    async def aclose(self) -> None:
        await self._client.aclose()
