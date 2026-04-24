"""NDJSON request logger — one JSON line per chat request for greppability."""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_lock = threading.Lock()
_log = logging.getLogger("ask-my-agent")


def configure(level: str = "INFO") -> None:
    """Set up stdout logging with a clean one-line format."""
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def write_event(path: Path, event: dict[str, Any]) -> None:
    """Append a JSON line to the request log, creating parent dirs if needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    event = {"ts": datetime.now(timezone.utc).isoformat(), **event}
    line = json.dumps(event, default=str, ensure_ascii=False)
    with _lock:
        with path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    _log.debug("logged event: %s", event.get("event"))


def read_recent_chats(path: Path, n: int = 5) -> list[dict[str, Any]]:
    """Return the last *n* first-turn chat events from the NDJSON log."""
    if not path.exists():
        return []
    events: list[dict[str, Any]] = []
    try:
        with path.open(encoding="utf-8") as fh:
            for raw in fh:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    ev = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if ev.get("event") == "chat" and ev.get("turn") == 1:
                    events.append(ev)
    except OSError:
        return []
    return events[-n:]
