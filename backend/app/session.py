"""In-process session + rate-limit state.

State resets on restart — acceptable for a single-container NAS deploy per
PRD §4. Keyed by `ip:token` for conversation counting and by `session_id`
for turn counting within a conversation.
"""

from __future__ import annotations

import threading
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal

from .config import Tier

# --- Limits per tier (PRD §4) ------------------------------------------------

# unlimited represented by -1
TIER_LIMITS: dict[Tier, tuple[int, int]] = {
    # (conversations/day/IP, turns/conversation)
    "public": (3, 10),
    "work": (10, 25),
    "friends": (10, 25),
    "personal": (-1, -1),
}


def conv_limit(tier: Tier) -> int:
    return TIER_LIMITS[tier][0]


def turn_limit(tier: Tier) -> int:
    return TIER_LIMITS[tier][1]


# --- State -------------------------------------------------------------------


@dataclass
class SessionState:
    session_id: str
    ip: str
    token: str
    tier: Tier
    turns: int = 0
    started_at: float = field(default_factory=time.time)
    closed: bool = False


class SessionStore:
    """Thread-safe in-memory session + conversation counter."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sessions: dict[str, SessionState] = {}
        # {ip:token → {YYYY-MM-DD: count}}
        self._conv_daily: dict[str, dict[str, int]] = defaultdict(dict)

    # ----- session lifecycle -------------------------------------------------

    def start_or_get(self, session_id: str | None, ip: str, token: str, tier: Tier) -> SessionState:
        """Either return an existing session or create a new one and count it."""
        with self._lock:
            if session_id and session_id in self._sessions:
                return self._sessions[session_id]
            new_id = session_id or str(uuid.uuid4())
            state = SessionState(session_id=new_id, ip=ip, token=token, tier=tier)
            self._sessions[new_id] = state
            self._count_conversation(ip, token)
            return state

    def _count_conversation(self, ip: str, token: str) -> None:
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        key = f"{ip}:{token}"
        bucket = self._conv_daily[key]
        bucket[day] = bucket.get(day, 0) + 1
        # Opportunistic cleanup: drop days older than today to keep memory bounded.
        for k in [k for k in bucket if k != day]:
            bucket.pop(k, None)

    def conversations_today(self, ip: str, token: str) -> int:
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return self._conv_daily.get(f"{ip}:{token}", {}).get(day, 0)

    def bump_turn(self, session_id: str) -> int:
        """Increment turn counter and return the new turn number."""
        with self._lock:
            state = self._sessions[session_id]
            state.turns += 1
            return state.turns

    def close(self, session_id: str) -> None:
        with self._lock:
            if session_id in self._sessions:
                self._sessions[session_id].closed = True

    def get(self, session_id: str) -> SessionState | None:
        return self._sessions.get(session_id)

    def active_sessions(self) -> list[SessionState]:
        """Return all non-closed sessions, most recent first."""
        with self._lock:
            return sorted(
                [s for s in self._sessions.values() if not s.closed],
                key=lambda s: s.started_at,
                reverse=True,
            )

    # ----- quota decisions ---------------------------------------------------

    def check_conversation_quota(
        self, tier: Tier, ip: str, token: str
    ) -> tuple[bool, int, int]:
        """Return `(allowed, used, limit)`. `limit=-1` means unlimited."""
        limit = conv_limit(tier)
        used = self.conversations_today(ip, token)
        if limit < 0:
            return True, used, limit
        return used < limit, used, limit

    def check_turn_quota(self, tier: Tier, state: SessionState) -> tuple[bool, int, int]:
        """Return `(would_be_allowed_on_next_turn, current_turns, limit)`."""
        limit = turn_limit(tier)
        if limit < 0:
            return True, state.turns, limit
        return state.turns < limit, state.turns, limit


# single process-wide store
store = SessionStore()

__all__ = ["SessionState", "SessionStore", "store", "TIER_LIMITS", "conv_limit", "turn_limit"]
