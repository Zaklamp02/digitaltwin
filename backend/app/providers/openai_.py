"""OpenAI provider."""

from __future__ import annotations

import logging
from typing import AsyncIterator

from openai import AsyncOpenAI

from .base import Message

log = logging.getLogger("ask-my-agent.openai")


class OpenAIProvider:
    name = "openai"

    def __init__(self, api_key: str, model: str = "gpt-4o-mini") -> None:
        self._client = AsyncOpenAI(api_key=api_key)
        self.model = model

    async def stream(
        self,
        system: str,
        messages: list[Message],
        max_tokens: int = 800,
    ) -> AsyncIterator[tuple[str, dict]]:
        openai_msgs = [{"role": "system", "content": system}] + [
            {"role": m.role, "content": m.content} for m in messages
        ]
        input_tokens = output_tokens = 0
        # gpt-5.x and o-series models require max_completion_tokens instead of max_tokens
        _use_completion_tokens = self.model.startswith(("gpt-5", "o1", "o3"))
        create_kwargs: dict = {
            "model": self.model,
            "messages": openai_msgs,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if _use_completion_tokens:
            create_kwargs["max_completion_tokens"] = max_tokens
        else:
            create_kwargs["max_tokens"] = max_tokens
        stream = await self._client.chat.completions.create(**create_kwargs)
        async for chunk in stream:
            if chunk.choices:
                delta = chunk.choices[0].delta.content or ""
                if delta:
                    yield delta, {}
            if chunk.usage:
                input_tokens = chunk.usage.prompt_tokens or 0
                output_tokens = chunk.usage.completion_tokens or 0
        yield "", {
            "provider": self.name,
            "model": self.model,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
        }
