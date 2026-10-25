"""Authoritative state; model work never holds a session guard."""

import asyncio
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Protocol
from uuid import uuid4

from backend.common.errors import Conflict, InvalidInput, Unavailable
from backend.integrations.llm.structured_generation import StructuredGeneration
from backend.modules.pre_interview.preparation.service import PreparationService

from .analysis import ANALYSIS_INSTRUCTION, InterviewAnalysis
from .assessment import AnswerAssessment
from .models import AgentEvent, AnswerResult, AnswerTurn, PublicSession, SessionState, TurnInput
from .reasoning import Reasoner
from .sessions import SessionRegistry
from .transitions import close, expire, new_session, require_prompt, transition


class HistoryStore(Protocol):
    def save(self, state: SessionState) -> None: ...
    def load(self, session_id: str) -> dict[str, object]: ...


class LiveInterviewService:
    def __init__(
        self,
        sessions: SessionRegistry,
        preparation: PreparationService,
        reasoner: Reasoner | None,
        *,
        clock: Callable[[], float] = time.time,
        timeout: float = 8,
        history: HistoryStore | None = None,
        analysis_generator: StructuredGeneration | None = None,
    ):
        self._sessions, self._preparation = sessions, preparation
        self._clock, self._history = clock, history
        self._assessment = AnswerAssessment(reasoner, timeout)
        self._tasks: dict[str, asyncio.Task[object]] = {}
        self._analysis_generator = analysis_generator
        self._analyses: dict[str, InterviewAnalysis] = {}
        self._analysis_locks: dict[str, asyncio.Lock] = {}

    async def analyze(self, session_id: str) -> InterviewAnalysis:
        history = self.history(session_id)
        session = history.get("session", {})
        if not isinstance(session, dict) or session.get("status") not in {"completed", "failed"}:
            raise Conflict("End the interview before viewing its analysis.")
        events = history.get("events", [])
        transcript = [
            event for event in events if isinstance(event, dict)
            and event.get("kind") in {"question", "candidate", "answer"}
        ] if isinstance(events, list) else []
        if not any(
            event.get("kind") in {"candidate", "answer"} and str(event.get("text", "")).strip()
            for event in transcript
        ):
            raise InvalidInput("No candidate answers were saved for analysis.")
        if self._analysis_generator is None:
            raise Unavailable("Interview analysis is temporarily unavailable.")
        async with self._analysis_locks.setdefault(session_id, asyncio.Lock()):
            if session_id not in self._analyses:
                self._analyses[session_id] = await self._analysis_generator.generate(
                    ANALYSIS_INSTRUCTION,
                    {"session": session, "transcript": transcript},
                    InterviewAnalysis,
                )
            return self._analyses[session_id]

    def _save(self, state: SessionState) -> None:
        if state.status in {"completed", "failed"} and state.ended_at is None:
            state.ended_at = self._clock()
        if self._history:
            self._history.save(state)

    @contextmanager
    def operation(self, session_id: str) -> Iterator[SessionState]:
        with self._sessions.operation(session_id) as state:
            previous = state.status
            expire(state, self._clock())
            if (
                state.status == "active"
                and state.disconnected_at is None
                and state.agent_seen_at is not None
                and self._clock() - state.agent_seen_at > 15
            ):
                state.status = "failed"
                state.completion_reason = "voice_agent_disconnected"
                state.revision += 1
                state.pending_turn = None
            if state.status != previous:
                self._cancel(session_id)
                self._save(state)
            yield state

    def _cancel(self, session_id: str) -> None:
        task = self._tasks.get(session_id)
        if task and task is not asyncio.current_task():
            task.cancel()

    async def create(self, candidate_id: str) -> PublicSession:
        preparation = await self._preparation.get(candidate_id)
        self.expire_sessions()
        if self._sessions.has_open():
            raise Conflict("An interview is already open. End it before starting another.")
        state = new_session(uuid4().hex, preparation, self._clock(), uuid4().hex)
        self._sessions.add(state)
        self._save(state)
        return state.public()

    def get(self, session_id: str) -> PublicSession:
        with self.operation(session_id) as state:
            if state.status == "waiting" and self._clock() - state.section_started_at > 180:
                state.status = "failed"
                state.completion_reason = "voice_agent_not_ready"
                self._save(state)
            return state.public()

    def history(self, session_id: str) -> dict[str, object]:
        if self._history:
            value = self._history.load(session_id)
            saved = value.get("session")
            if (
                session_id not in self._sessions.ids()
                and isinstance(saved, dict)
                and saved.get("status") in {"waiting", "active"}
            ):
                saved["status"] = "failed"
                saved["completion_reason"] = "backend_restarted"
            return value
        with self.operation(session_id) as state:
            return {
                "session": state.public().model_dump(),
                "events": state.history,
                "evidence": [item.model_dump() for item in state.evidence],
            }

    def agent_state(self, session_id: str) -> PublicSession:
        with self.operation(session_id) as state:
            state.agent_seen_at = self._clock()
            return state.public()

    def event(self, session_id: str, event: AgentEvent) -> PublicSession:
        with self.operation(session_id) as state:
            if state.status in {"completed", "failed"} and event.kind != "playback":
                return state.public()
            now = self._clock()
            if event.kind == "ready":
                state.ready = True
                state.agent_seen_at = now
            elif event.kind == "joined":
                if not state.ready:
                    raise Conflict("The voice agent is still loading.")
                if state.status == "waiting":
                    state.status = "active"
                    state.section_started_at = now
                    state.deadline_at = now + state.preparation.settings.duration * 60
                state.disconnected_at = None
                state.agent_seen_at = now
            elif event.kind in {"invalidate", "disconnected", "failed"}:
                state.revision += 1
                state.pending_turn = None
                self._cancel(session_id)
                if event.kind == "disconnected":
                    state.disconnected_at = now
                elif event.kind == "failed":
                    state.status = "failed"
                    state.completion_reason = "voice_agent_failed"
            elif event.kind == "playback":
                state.history.append(
                    {
                        "kind": "question",
                        "text": event.text,
                        "prompt_id": event.prompt_id or "",
                        "interrupted": event.interrupted,
                        "at": now,
                    }
                )
            self._save(state)
            return state.public()

    async def answer_from_transcript(self, session_id: str, body: TurnInput) -> AnswerResult:
        if not body.text.strip():
            raise InvalidInput("No speech was recognized. Please try again.")
        task = asyncio.current_task()
        with self.operation(session_id) as state:
            if body.turn_id in state.turn_results:
                return state.turn_results[body.turn_id]
            require_prompt(state, body.prompt_id, self._clock())
            if state.pending_turn:
                raise Conflict("An answer is already being assessed.")
            self._assessment.require_available()
            state.pending_turn = body.turn_id
            revision = state.revision
            snapshot = state.model_copy(deep=True)
        if task:
            self._tasks[session_id] = task
        try:
            decision, available = await self._assessment.assess(
                snapshot, body.text.strip(), max(0, snapshot.deadline_at - self._clock())
            )
            with self.operation(session_id) as state:
                if state.revision != revision or state.pending_turn != body.turn_id:
                    raise Conflict("This answer was superseded by continued speech or session end.")
                require_prompt(state, body.prompt_id, self._clock())
                state.history.append(
                    {
                        "kind": "candidate",
                        "text": body.text.strip(),
                        "prompt_id": body.prompt_id,
                        "at": self._clock(),
                    }
                )
                if decision.intent in {"repeat", "clarification"}:
                    assert state.current_prompt
                    spoken = state.current_prompt.text
                    if decision.intent == "clarification":
                        spoken = decision.next_question or "Let me repeat the question. " + spoken
                    result = AnswerResult(session=state.public(), spoken_text=spoken)
                elif decision.intent == "stop":
                    close(state)
                    state.completion_reason = "candidate_stopped"
                    result = AnswerResult(
                        session=state.public(), spoken_text="Thank you. Your interview has ended."
                    )
                else:
                    state.answers.append(
                        AnswerTurn(question_id=state.question_id, answer=body.text.strip())
                    )
                    outcome = transition(state, decision, self._clock(), uuid4().hex, available)
                    if state.status == "completed":
                        state.completion_reason = outcome.reason
                    result = AnswerResult(
                        session=state.public(),
                        transition=outcome,
                        spoken_text=state.current_prompt.text
                        if state.current_prompt
                        else "Thank you. Your interview is complete.",
                    )
                state.pending_turn = None
                state.revision += 1
                state.turn_results[body.turn_id] = result
                self._save(state)
                return result
        finally:
            if self._tasks.get(session_id) is task:
                self._tasks.pop(session_id, None)
            with self.operation(session_id) as state:
                if state.pending_turn == body.turn_id:
                    state.pending_turn = None

    def end(self, session_id: str) -> PublicSession:
        with self.operation(session_id) as state:
            if state.status not in {"completed", "failed"}:
                self._cancel(session_id)
                close(state)
                state.completion_reason = "user_ended"
                self._save(state)
            return state.public()

    def expire_sessions(self) -> list[str]:
        ended = []
        for key in self._sessions.ids():
            if self.get(key).status in {"completed", "failed"}:
                with self._sessions.operation(key) as state:
                    if state.ended_at is not None and self._clock() - state.ended_at >= 5:
                        ended.append(key)
        return ended
