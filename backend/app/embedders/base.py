"""Embedder interface."""

from __future__ import annotations

from typing import Protocol


class Embedder(Protocol):
    """A thing that turns strings into fixed-length float vectors."""

    name: str

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch. Implementations may be sync or async-wrapped; keep sync for simplicity."""
        ...
