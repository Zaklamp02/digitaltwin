"""Anthropic provider (default)."""

from __future__ import annotations

import logging
from typing import AsyncIterator

from anthropic import AsyncAnthropic

from .base import Message

log = logging.getLogger("ask-my-agent.anthropic")


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, api_key: str, model: str = "claude-sonnet-4-6") -> None:
        self._client = AsyncAnthropic(api_key=api_key)
        self.model = model

    async def stream(
        self,
        system: str,
        messages: list[Message],
        max_tokens: int = 800,
    ) -> AsyncIterator[tuple[str, dict]]:
        anthropic_msgs = [{"role": m.role, "content": m.content} for m in messages]
        input_tokens = output_tokens = 0
        async with self._client.messages.stream(
            model=self.model,
            system=system,
            messages=anthropic_msgs,
            max_tokens=max_tokens,
        ) as stream:
            async for text in stream.text_stream:
                yield text, {}
            final = await stream.get_final_message()
            if final.usage:
                input_tokens = final.usage.input_tokens or 0
                output_tokens = final.usage.output_tokens or 0
        yield "", {
            "provider": self.name,
            "model": self.model,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
        }
