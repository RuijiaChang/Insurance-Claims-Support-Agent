"""In-memory session store with a TTL and one asyncio.Lock per session.

Single uvicorn worker only (spec §12); horizontal scaling would move this to Redis.
Session ids are server-generated uuid4 hex strings; any other shape is treated as
unknown, because ids end up in outbox file names.
"""

import asyncio
import re
import threading
import time
import uuid

from app.sop.state import SessionState

_ID_RE = re.compile(r"^[0-9a-f]{32}$")


def valid_session_id(session_id: str) -> bool:
    return _ID_RE.fullmatch(session_id) is not None


class SessionStore:
    def __init__(self, ttl_min: int) -> None:
        self.ttl_min = ttl_min
        self._sessions: dict[str, SessionState] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._touched: dict[str, float] = {}
        self._guard = threading.Lock()  # the store's own lock (spec §12)

    def _expired(self, session_id: str, now: float) -> bool:
        return now - self._touched.get(session_id, now) > self.ttl_min * 60

    def _purge(self, now: float) -> None:
        for session_id in [s for s in self._sessions if self._expired(s, now)]:
            self._drop(session_id)

    def _drop(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)
        self._locks.pop(session_id, None)
        self._touched.pop(session_id, None)

    def create(self, consent_scenario: str) -> SessionState:
        now = time.monotonic()
        with self._guard:
            self._purge(now)
            state = SessionState.new(uuid.uuid4().hex, consent_scenario)
            self._sessions[state.session_id] = state
            self._locks[state.session_id] = asyncio.Lock()
            self._touched[state.session_id] = now
            return state

    def get(self, session_id: str) -> SessionState | None:
        if not valid_session_id(session_id):
            return None
        now = time.monotonic()
        with self._guard:
            if session_id in self._sessions and self._expired(session_id, now):
                self._drop(session_id)
            state = self._sessions.get(session_id)
            if state is not None:
                self._touched[session_id] = now
            return state

    def delete(self, session_id: str) -> None:
        with self._guard:
            self._drop(session_id)

    def lock(self, session_id: str) -> asyncio.Lock:
        """The session's lock; an unknown id gets a throwaway lock (nothing to protect)."""
        with self._guard:
            return self._locks.get(session_id) or asyncio.Lock()
