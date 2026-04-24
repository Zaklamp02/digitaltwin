"""Shared fixtures — KnowledgeDB, fake embedder, isolated ChromaDB."""

from __future__ import annotations

from pathlib import Path
from typing import Iterator

import pytest

from app.knowledge import KnowledgeDB


@pytest.fixture
def tmp_memory_dir(tmp_path: Path) -> Path:
    """A memory directory with three tiers, laid out like the real thing.

    Still used by migrate_from_memory() at startup to seed a KnowledgeDB.
    """
    d = tmp_path / "memory"
    d.mkdir()
    (d / "_system.md").write_text(
        "<!-- tier: system -->\n# System\nYou are a test agent.\n", encoding="utf-8"
    )
    (d / "public_bio.md").write_text(
        "<!-- tier: public -->\n"
        "# Sebastiaan\n\n"
        "Sebastiaan is a director of AI and lives in Utrecht. "
        "He founded the AI practice at Youwe in 2023.\n",
        encoding="utf-8",
    )
    (d / "recruiter_personality.md").write_text(
        "<!-- tier: recruiter -->\n"
        "# Personality\n\n"
        "Dutch directness. KPI-driven. Warm but will push back.\n",
        encoding="utf-8",
    )
    personal = d / "personal"
    personal.mkdir()
    (personal / "anecdote.md").write_text(
        "<!-- tier: personal -->\n"
        "# First week at Youwe\n\n"
        "The inner-circle story about how the AI team was one person on day one.\n",
        encoding="utf-8",
    )
    return d


@pytest.fixture
def tmp_knowledge_db(tmp_path: Path, tmp_memory_dir: Path) -> KnowledgeDB:
    """A KnowledgeDB seeded from tmp_memory_dir, for use in RAG and chat tests."""
    from app.knowledge import migrate_from_memory

    db_path = tmp_path / "test_knowledge.db"
    db = KnowledgeDB(db_path)
    migrate_from_memory(tmp_memory_dir, db)
    return db


class FakeEmbedder:
    """Deterministic tiny embedder: bag-of-words hash into a 64-dim vector."""

    name = "fake"

    def embed(self, texts: list[str]) -> list[list[float]]:
        import hashlib

        out: list[list[float]] = []
        for t in texts:
            vec = [0.0] * 64
            for word in t.lower().split():
                h = int(hashlib.md5(word.encode()).hexdigest()[:8], 16)
                vec[h % 64] += 1.0
            # L2 normalise
            norm = sum(v * v for v in vec) ** 0.5 or 1.0
            out.append([v / norm for v in vec])
        return out


@pytest.fixture
def fake_embedder() -> FakeEmbedder:
    return FakeEmbedder()


@pytest.fixture
def isolated_chroma_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Isolate ChromaDB to the temp dir and pin settings to it."""
    chroma = tmp_path / "chroma_db"
    chroma.mkdir()
    yield chroma
