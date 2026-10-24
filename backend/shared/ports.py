from collections.abc import Callable
from typing import Protocol, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class LanguageModel(Protocol):
    async def generate(
        self,
        instruction: str,
        content: dict,
        schema: type[T],
        check: Callable[[T], None] | None = None,
    ) -> T: ...


class ChatModel(Protocol):
    async def complete(
        self, messages: list[dict], *, timeout: float = 120, max_tokens: int = 8192
    ) -> str: ...
