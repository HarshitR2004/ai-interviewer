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
    def __init__(self, client: ChatCompletionClient, *, timeout: float = 8):
        self._client, self._timeout = client, timeout

    async def assess(self, state: SessionState, answer: str, remaining_seconds: float) -> Decision:
        # Ask the model for an assessment using this question's answer turns and recent evidence.
        assert state.current_prompt is not None
        content = {
            "role": state.preparation.plan.role,
            **({"job_description": state.preparation.job_description}
               if state.section.kind == "closing" else {}),
            "seniority": state.preparation.settings.seniority,
            "section_type": state.section.kind,
            "assessed": state.section.scored,
            "competencies": [state.section.competency, *state.section.covered_competencies],
            "section_remaining_seconds": max(
                0,
                state.section_started_at
                + state.section.minutes * 60
                - (state.deadline_at - remaining_seconds),
            ),
            "recent_conversation": [
                {"speaker": item["kind"], "text": str(item["text"])[:1200]}
                for item in state.history[-6:]
                if "text" in item and "kind" in item
            ],
            "question": state.question.model_dump(),
            "prompt": state.current_prompt.text,
            "answer": answer,
            "earlier_evidence": [item.model_dump() for item in state.evidence[-6:]],
            "answer_turns": [
                item.answer for item in state.answers if item.question_id == state.question_id
            ],
            "follow_ups_used": state.follow_up_count,
            "remaining_seconds": remaining_seconds,
        }
        raw = await self._client.complete(
            [
                {
                    "role": "system",
                    "content": ASSESSMENT,
                },
                {"role": "user", "content": json.dumps(content)},
            ],
            timeout=self._timeout,
            # Some compatible reasoning models count hidden reasoning in this budget.
            # Keep the spoken JSON concise while leaving room for that provider overhead.
            max_tokens=2048,
        )
        decision = Decision.model_validate_json(raw)
        if not state.section.scored:
            decision.evidence = []
            decision.missing_evidence = []
            if decision.intent == "answer":
                decision.action = "advance"
                decision.next_question = None
        return decision
