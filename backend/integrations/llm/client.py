"""OpenAI-compatible HTTP transport. No output repair or domain validation here."""

import logging

import httpx
from pydantic import SecretStr

from backend.common.errors import Unavailable

log = logging.getLogger(__name__)


class ChatCompletionsClient:
    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: SecretStr | str | None = None,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        secret = api_key.get_secret_value() if isinstance(api_key, SecretStr) else api_key
        self.model = model
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/") + "/",
            transport=transport,
            trust_env=False,
            headers={"Authorization": f"Bearer {secret}"} if secret else {},
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def complete(
        self,
        messages: list[dict[str, str]],
        *,
        timeout: float = 120,
        max_tokens: int = 8192,
    ) -> str:
        # Request JSON output and translate transport or malformed-envelope failures.
        try:
            response = await self._client.post(
                "chat/completions",
                timeout=httpx.Timeout(timeout, connect=min(timeout, 10)),
                json={
                    "model": self.model,
                    "messages": messages,
                    "stream": False,
                    "temperature": 0.1,
                    "max_tokens": max_tokens,
                    "response_format": {"type": "json_object"},
                },
            )
            response.raise_for_status()
            body = response.json()
            if not isinstance(body, dict) or body.get("error"):
                raise ValueError("Invalid provider envelope")
            choice = body["choices"][0]
            if not isinstance(choice, dict) or choice.get("finish_reason") == "length":
                raise ValueError("Invalid or truncated choice")
            raw = choice["message"]["content"]
            if not isinstance(raw, str) or not raw.strip():
                raise ValueError("Empty provider output")
            return raw
        except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError) as exc:
            log.warning("LLM transport failed (%s)", type(exc).__name__)
            raise Unavailable(
                "LLM generation is temporarily unavailable. Please try again."
            ) from exc
