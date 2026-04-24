"""Ollama provider — OpenAI-compatible local LLM via http://host.docker.internal:11434."""

from __future__ import annotations

import logging
from typing import AsyncIterator

from openai import AsyncOpenAI

from .base import Message

log = logging.getLogger("ask-my-agent.ollama")


class OllamaProvider:
    name = "ollama"

    def __init__(self, base_url: str = "http://host.docker.internal:11434", model: str = "llama3.2") -> None:
        # Ollama exposes an OpenAI-compatible /v1 endpoint
        self._client = AsyncOpenAI(
            api_key="ollama",           # required by client but ignored by Ollama
            base_url=f"{base_url.rstrip('/')}/v1",
        )
        self.model = model

    async def stream(
        self,
        system: str,
        messages: list[Message],
        max_tokens: int = 800,
    ) -> AsyncIterator[tuple[str, dict]]:
        ollama_msgs = [{"role": "system", "content": system}] + [
            {"role": m.role, "content": m.content} for m in messages
        ]
        input_tokens = output_tokens = 0
        stream = await self._client.chat.completions.create(
            model=self.model,
            messages=ollama_msgs,
            max_tokens=max_tokens,
            stream=True,
        )
        async for chunk in stream:
            if chunk.choices:
                delta = chunk.choices[0].delta.content or ""
                if delta:
                    yield delta, {}
            # Ollama may include usage in the final chunk
            if hasattr(chunk, "usage") and chunk.usage:
                input_tokens = getattr(chunk.usage, "prompt_tokens", 0) or 0
                output_tokens = getattr(chunk.usage, "completion_tokens", 0) or 0
        yield "", {
            "provider": self.name,
            "model": self.model,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
        }
