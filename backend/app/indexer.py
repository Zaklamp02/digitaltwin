"""Chunk knowledge nodes and upsert into ChromaDB with role metadata.

Strategy:
- Split on markdown headings (##, ###) first.
- Further split oversized sections into token-limited windows with overlap.
- Token count uses tiktoken's cl100k_base (good approximation for both OpenAI
  and Anthropic; we only use it to bound chunk size).
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import Tier
from .embedders import Embedder

log = logging.getLogger("ask-my-agent.indexer")


class _Tokenizer:
    """Thin wrapper: tries tiktoken (cl100k_base), falls back to char-based count.

    The fallback is only used when tiktoken's encoding can't be loaded (e.g.
    no network at first boot and no cached encoding). It's a rough
    approximation — 1 token ≈ 4 characters for English prose — and is good
    enough for chunk sizing.
    """

    def __init__(self) -> None:
        self._enc: Any | None = None
        self._tried = False

    def _enc_or_none(self) -> Any | None:
        if self._tried:
            return self._enc
        self._tried = True
        try:
            import tiktoken  # type: ignore[import-untyped]

            self._enc = tiktoken.get_encoding("cl100k_base")
        except Exception as exc:  # noqa: BLE001
            log.warning("tiktoken unavailable, falling back to char-based counting: %s", exc)
            self._enc = None
        return self._enc

    def encode(self, text: str) -> list[int]:
        enc = self._enc_or_none()
        if enc is not None:
            return enc.encode(text)
        # Fallback: one "token" per 4 chars, rounded up.
        return list(range((len(text) + 3) // 4))

    def decode(self, ids: list[int]) -> str:  # only meaningful with real tiktoken
        enc = self._enc_or_none()
        if enc is not None:
            return enc.decode(ids)
        # Fallback can't round-trip; callers in this module only decode when
        # tiktoken is present because _window_by_tokens relies on it.
        raise RuntimeError("decode called with no tokenizer available")


_tok = _Tokenizer()

HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$", re.MULTILINE)


# --- chunking ---------------------------------------------------------------


@dataclass
class Chunk:
    id: str
    file: str
    section_heading: str
    chunk_index: int
    tier: Tier
    roles: list[str]       # RBAC roles — pipe-joined in ChromaDB metadata
    memory_type: str       # factual|experience|project|opinion|personal|faq|community
    text: str


def _token_count(text: str) -> int:
    return len(_tok.encode(text))


def _split_by_headings(body: str) -> list[tuple[str, str]]:
    """Return list of (heading, section_body). Prefaces with empty heading if
    content exists before the first heading."""
    sections: list[tuple[str, str]] = []
    matches = list(HEADING_RE.finditer(body))
    if not matches:
        return [("", body.strip())] if body.strip() else []

    first_start = matches[0].start()
    preface = body[:first_start].strip()
    if preface:
        sections.append(("", preface))

    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        heading = m.group(2).strip()
        section_body = body[m.end():end].strip()
        if section_body or heading:
            sections.append((heading, section_body))
    return sections


def _window_by_tokens(text: str, max_tokens: int, overlap: int) -> list[str]:
    """Split a long text into overlapping token windows.

    Uses tiktoken when available for precise token-boundary splits. Falls
    back to a paragraph/sentence-greedy split when tiktoken can't be loaded
    so chunks never exceed roughly `max_tokens` worth of characters.
    """
    if not text.strip():
        return []
    enc = _tok._enc_or_none()
    if enc is not None:
        ids = enc.encode(text)
        if len(ids) <= max_tokens:
            return [text]
        step = max(1, max_tokens - overlap)
        windows: list[str] = []
        for start in range(0, len(ids), step):
            slice_ids = ids[start:start + max_tokens]
            if not slice_ids:
                break
            windows.append(enc.decode(slice_ids))
            if start + max_tokens >= len(ids):
                break
        return windows
    # --- character-based fallback (no tiktoken) ------------------------------
    max_chars = max_tokens * 4
    if len(text) <= max_chars:
        return [text]
    overlap_chars = overlap * 4
    step = max(1, max_chars - overlap_chars)
    return [text[i:i + max_chars] for i in range(0, len(text), step)]


def chunk_node(node: "KnowledgeNode", chunk_tokens: int, overlap: int) -> list[Chunk]:  # type: ignore[name-defined]
    """Split a KnowledgeNode into chunks with role metadata."""
    from .knowledge import KnowledgeNode  # local import to avoid circular dep

    chunks: list[Chunk] = []
    sections = _split_by_headings(node.body)
    # Derive a legacy tier from roles for backward-compat metadata
    if "personal" in node.roles:
        tier: Tier = "personal"
    elif "friends" in node.roles or "work" in node.roles or "recruiter" in node.roles:
        tier = "work"
    else:
        tier = "public"
    idx = 0
    for heading, body in sections:
        for window in _window_by_tokens(body, chunk_tokens, overlap):
            if not window.strip():
                continue
            text = f"# {heading}\n\n{window}".strip() if heading else window.strip()
            chunk_id = _chunk_id(f"node:{node.id}", idx, text)
            chunks.append(
                Chunk(
                    id=chunk_id,
                    file=f"node:{node.id}",
                    section_heading=heading,
                    chunk_index=idx,
                    tier=tier,
                    roles=node.roles,
                    memory_type=node.type,
                    text=text,
                )
            )
            idx += 1
    return chunks


def _chunk_id(rel_path: str, chunk_index: int, text: str) -> str:
    h = hashlib.sha1(text.encode("utf-8")).hexdigest()[:8]
    return f"{rel_path}::{chunk_index}::{h}"


# --- ChromaDB upsert ---------------------------------------------------------


def upsert_chunks(collection, embedder: Embedder, chunks: list[Chunk]) -> None:
    """Embed and upsert a list of chunks into a ChromaDB collection."""
    if not chunks:
        return
    texts = [c.text for c in chunks]
    vectors = embedder.embed(texts)
    collection.upsert(
        ids=[c.id for c in chunks],
        documents=texts,
        embeddings=vectors,
        metadatas=[
            {
                "file": c.file,
                "section_heading": c.section_heading,
                "chunk_index": c.chunk_index,
                "tier": c.tier,
                "roles": "|".join(c.roles),          # pipe-joined for storage
                "memory_type": c.memory_type,
            }
            for c in chunks
        ],
    )
    log.info("upserted %d chunks", len(chunks))


def delete_node_chunks(collection, node_id: str) -> None:
    """Delete all chunks belonging to a knowledge node."""
    collection.delete(where={"file": f"node:{node_id}"})
    log.info("deleted chunks for node %s", node_id)


__all__ = ["Chunk", "chunk_node", "upsert_chunks", "delete_node_chunks"]
