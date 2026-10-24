from collections.abc import Callable
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class ChatCompletionClient(Protocol):
    async def complete(
        self, messages: list[dict[str, str]], *, timeout: float = 120, max_tokens: int = 8192
    ) -> str: ...


class StructuredGenerator(Protocol):
    async def generate(
        self,
        instruction: str,
        content: dict[str, Any],
        schema: type[T],
        check: Callable[[T], None] | None = None,
    ) -> T: ...
