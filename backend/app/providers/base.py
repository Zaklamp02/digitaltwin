"""LLMProvider protocol — both providers implement this."""

from __future__ import annotations

from dataclasses import dataclass
from typing import AsyncIterator, Literal, Protocol

Role = Literal["user", "assistant"]


@dataclass
class Message:
    role: Role
    content: str


class LLMProvider(Protocol):
    name: str
    model: str

    async def stream(
        self,
        system: str,
        messages: list[Message],
        max_tokens: int = 800,
    ) -> AsyncIterator[tuple[str, dict]]:
        """Yield ``(token, meta)`` tuples. `meta` may carry final usage stats
        in the last yielded tuple (token == "" then)."""
        ...
