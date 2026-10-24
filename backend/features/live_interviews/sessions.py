from collections.abc import Iterator
from contextlib import contextmanager

from backend.common.errors import Conflict, NotFound

from .models import SessionState


class SessionRegistry:
    def __init__(self) -> None:
        self._sessions: dict[str, SessionState] = {}
        self._busy: set[str] = set()

    def add(self, state: SessionState) -> None:
        self._sessions[state.session_id] = state

    @contextmanager
    def operation(self, session_id: str) -> Iterator[SessionState]:
        if session_id in self._busy:
            raise Conflict("This interview is busy. Wait for the current operation to finish.")
        if session_id not in self._sessions:
            raise NotFound(
                "Interview session not found. Sessions are lost when the server restarts."
            )
        self._busy.add(session_id)
        try:
            yield self._sessions[session_id]
        finally:
            self._busy.remove(session_id)
