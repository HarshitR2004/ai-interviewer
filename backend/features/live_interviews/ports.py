from typing import Protocol

from .models import Decision


class Reasoner(Protocol):
    async def assess(self, snapshot: dict, answer: str) -> Decision: ...


class PlanSource(Protocol):
    async def load(self, candidate_id: str) -> dict: ...
