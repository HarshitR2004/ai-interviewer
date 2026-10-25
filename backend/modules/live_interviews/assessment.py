"""Provider assessment, timeout handling, and deterministic failure recovery."""

import asyncio
import logging

from backend.common.errors import Unavailable

from .models import Decision, SessionState
from .reasoning import Reasoner
from .transitions import fallback

log = logging.getLogger(__name__)


class AnswerAssessment:
    def __init__(self, reasoner: Reasoner | None, timeout: float):
        self._reasoner, self._timeout = reasoner, timeout

    def require_available(self) -> None:
        if self._reasoner is None:
            raise Unavailable("Live reasoning is disabled. No answer was saved.")

    async def assess(
        self, state: SessionState, answer: str, remaining_seconds: float
    ) -> tuple[Decision, bool]:
        self.require_available()
        assert self._reasoner is not None
        control = answer.lower().strip().rstrip(".!?")
        if control in {
            "repeat",
            "repeat the question",
            "please repeat the question",
            "could you repeat that",
            "can you repeat the question",
        }:
            return Decision(action="advance", intent="repeat"), True
        if control in {"stop the interview", "end the interview", "please stop the interview"}:
            return Decision(action="finish", intent="stop"), True
        clarification = control in {
            "what do you mean",
            "please clarify",
            "can you clarify the question",
        }
        available = True
        try:
            decision = Decision.model_validate(
                await asyncio.wait_for(
                    self._reasoner.assess(
                        # Isolate provider assessment from the mutable live session.
                        state.model_copy(deep=True),
                        answer,
                        remaining_seconds,
                    ),
                    self._timeout,
                )
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.warning("Assessment unavailable (%s)", type(exc).__name__)
            available = False
            decision = (
                Decision(action="advance", intent="repeat") if clarification else fallback(state)
            )
        return decision, available
