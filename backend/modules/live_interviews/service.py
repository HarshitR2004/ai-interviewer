import asyncio
import logging
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from uuid import uuid4

from backend.common.errors import Conflict, Unavailable
from backend.modules.pre_interview.preparation.service import PreparationService

from .models import AnswerInput, AnswerResult, AnswerTurn, Decision, PublicSession, SessionState
from .reasoning import Reasoner
from .sessions import SessionRegistry
from .transitions import close, fallback, new_session, transition

log = logging.getLogger(__name__)


class LiveInterviewService:
    def __init__(
        self,
        sessions: SessionRegistry,
        preparation: PreparationService,
        reasoner: Reasoner | None,
        *,
        clock: Callable[[], float] = time.time,
        timeout: float = 60,
    ):
        self._sessions, self._preparation, self._reasoner = sessions, preparation, reasoner
        self._clock, self._timeout = clock, timeout

    @contextmanager
    def operation(self, session_id: str) -> Iterator[SessionState]:
        # Hold exclusive session access and close expired interviews before use.
        with self._sessions.operation(session_id) as state:
            if state.status == "active" and self._clock() >= state.deadline_at:
                close(state)
            yield state

    async def create(self, candidate_id: str) -> PublicSession:
        # Snapshot a saved preparation into a new in-memory interview session.
        preparation = await self._preparation.get(candidate_id)
        state = new_session(uuid4().hex, preparation, self._clock(), uuid4().hex)
        self._sessions.add(state)
        return state.public()

    def get(self, session_id: str) -> PublicSession:
        # Expose public progress while applying the session expiry rules.
        with self.operation(session_id) as state:
            return state.public()

    def require_prompt(self, state: SessionState, prompt_id: str) -> None:
        # Reject expired sessions and answers targeting an outdated prompt.
        if state.status != "active" or self._clock() >= state.deadline_at:
            close(state)
            raise Conflict("Interview is no longer accepting answers.")
        if state.current_prompt is None or state.current_prompt.id != prompt_id:
            raise Conflict("This prompt is no longer current.")

    async def answer(self, session_id: str, body: AnswerInput) -> AnswerResult:
        # Keep the session guard held throughout text-answer assessment.
        with self.operation(session_id) as state:
            return await self.assess_answer(state, body)

    def require_reasoning(self) -> None:
        # Fail before saving an answer when live assessment is disabled.
        if self._reasoner is None:
            raise Unavailable("Live reasoning is disabled. No answer was saved.")

    async def assess_answer(self, state: SessionState, body: AnswerInput) -> AnswerResult:
        """Shared text/audio operation; caller holds the session operation guard."""
        self.require_prompt(state, body.prompt_id)
        self.require_reasoning()
        assert self._reasoner is not None
        available = True
        try:
            decision = Decision.model_validate(
                await asyncio.wait_for(
                    self._reasoner.assess(
                        # Isolate provider assessment from the mutable live session.
                        state.model_copy(deep=True),
                        body.answer,
                        max(0, state.deadline_at - self._clock()),
                    ),
                    self._timeout,
                )
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.warning("Assessment unavailable (%s)", type(exc).__name__)
            available = False
            decision = fallback(state)
        # No state mutation occurs before provider work finishes. Cancellation is safe to retry.
        state.answers.append(AnswerTurn(question_id=state.question_id, answer=body.answer))
        outcome = transition(state, decision, self._clock(), uuid4().hex, available)
        return AnswerResult(session=state.public(), transition=outcome)

    def end(self, session_id: str) -> PublicSession:
        # Close the interview under the same guard used for answers.
        with self.operation(session_id) as state:
            close(state)
            return state.public()
