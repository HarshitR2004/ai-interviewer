import json
from typing import Protocol

from backend.integrations.llm.contracts import ChatCompletionClient

from .models import Decision, SessionState
from .prompts import ASSESSMENT


class Reasoner(Protocol):
    async def assess(
        self, state: SessionState, answer: str, remaining_seconds: float
    ) -> Decision: ...


class ModelReasoner:
    def __init__(self, client: ChatCompletionClient, *, timeout: float = 60):
        self._client, self._timeout = client, timeout

    async def assess(self, state: SessionState, answer: str, remaining_seconds: float) -> Decision:
        assert state.current_prompt is not None
        content = {
            "role": state.preparation.plan.role,
            "question": state.question.model_dump(),
            "prompt": state.current_prompt.text,
            "answer": answer,
            "earlier_evidence": [item.model_dump() for item in state.evidence[-6:]],
            "answer_turns": [
                item.answer for item in state.answers if item.question_id == state.question_id
            ]
            + [answer],
            "follow_ups_used": state.follow_up_count,
            "remaining_seconds": remaining_seconds,
        }
        raw = await self._client.complete(
            [
                {
                    "role": "system",
                    "content": ASSESSMENT + "\n" + json.dumps(Decision.model_json_schema()),
                },
                {"role": "user", "content": json.dumps(content)},
            ],
            timeout=self._timeout,
        )
        return Decision.model_validate_json(raw)
