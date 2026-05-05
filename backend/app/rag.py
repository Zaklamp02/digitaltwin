"""RAGRetriever — contextual query + role-filtered retrieval."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import chromadb

from .config import Settings, Tier
from .embedders import Embedder, LocalEmbedder, OpenAIEmbedder
from .indexer import chunk_node, delete_node_chunks, upsert_chunks

log = logging.getLogger("ask-my-agent.rag")

COLLECTION_NAME = "memory_palace"


@dataclass
class RetrievedChunk:
    file: str
    section_heading: str
    tier: Tier
    roles: list[str]
    memory_type: str
    score: float
    text: str
    image_path: str = ""   # non-empty for image-type chunks


def build_embedder(settings: Settings) -> Embedder:
    """Pick an embedder based on settings."""
    if settings.embedding_provider == "openai":
        if not settings.openai_api_key:
            raise RuntimeError("EMBEDDING_PROVIDER=openai but OPENAI_API_KEY not set")
        return OpenAIEmbedder(api_key=settings.openai_api_key, model=settings.embedding_model)
    return LocalEmbedder(model_name=settings.local_embedding_model)


class RAGRetriever:
    """Owns the ChromaDB collection and wires it to the KnowledgeDB."""

    def __init__(
        self,
        settings: Settings,
        embedder: Embedder,
        knowledge: "KnowledgeDB",  # type: ignore[name-defined]
    ) -> None:
        self.settings = settings
        self._knowledge = knowledge
        self.embedder = embedder
        self._client = chromadb.PersistentClient(path=str(settings.chroma_path))
        self._collection = self._client.get_or_create_collection(
            name=COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},
        )

    # ----- indexing ----------------------------------------------------------

    def reindex_all(self) -> int:
        """Full reindex from the KnowledgeDB."""
        return self._reindex_from_knowledge()

    def _reindex_from_knowledge(self) -> int:
        """Index all non-system nodes from the KnowledgeDB."""
        total = 0
        # Wipe chunks for nodes that no longer exist
        existing = self._collection.get(include=["metadatas"])
        known_node_ids = {
            f"node:{n.id}"
            for n in self._knowledge.list_nodes()
            if n.type != "system"
        }
        for meta in existing.get("metadatas") or []:
            f = (meta or {}).get("file", "")
            if f.startswith("node:"):
                if f not in known_node_ids:
                    delete_node_chunks(self._collection, f[len("node:"):])
        for node in self._knowledge.list_nodes():
            if node.type == "system":
                continue  # system prompt is not RAG-indexed
            total += self._reindex_node(node)
        log.info("reindex: %d chunks across %d nodes", total, self._knowledge.node_count())
        return total

    def _reindex_node(self, node: Any) -> int:
        delete_node_chunks(self._collection, node.id)
        chunks = chunk_node(node, self.settings.chunk_tokens, self.settings.chunk_overlap)
        upsert_chunks(self._collection, self.embedder, chunks)
        return len(chunks)

    # ----- node-triggered reindex (called from admin API) --------------------

    def reindex_node(self, node: Any) -> int:
        """Re-index a single node after it has been created/updated."""
        return self._reindex_node(node)

    def delete_node_from_index(self, node_id: str) -> None:
        """Remove a node's chunks from the vector index."""
        delete_node_chunks(self._collection, node_id)

    # ----- retrieval ---------------------------------------------------------

    @staticmethod
    def contextual_query(user_turns: list[str], n: int) -> str:
        """Build an embedding query from the latest user turn only.

        Using only the latest turn (rather than concatenating multiple turns) keeps
        the embedding anchored on what was actually asked.  Prior turns are already
        available to the LLM via conversation history; polluting the retrieval query
        with them causes unrelated context to dominate and relevant chunks to fall
        below the score threshold.
        """
        clean = [t for t in user_turns if t and t.strip()]
        return clean[-1] if clean else ""

    def retrieve(
        self,
        user_turns: list[str],
        caller_roles: list[str] | None = None,
    ) -> list[RetrievedChunk]:
        query = self.contextual_query(user_turns, self.settings.rag_context_turns)
        if not query:
            return []
        # Resolve which roles the caller has
        roles: set[str] = set(caller_roles or [])

        vec = self.embedder.embed([query])[0]
        # Over-fetch so post-filtering still leaves enough results
        n_fetch = max(self.settings.rag_top_k * 4, 20)
        try:
            res = self._collection.query(
                query_embeddings=[vec],
                n_results=n_fetch,
                include=["documents", "metadatas", "distances"],
            )
        except Exception:
            # Collection may be empty; return gracefully
            return []
        out: list[RetrievedChunk] = []
        docs = (res.get("documents") or [[]])[0]
        metas = (res.get("metadatas") or [[]])[0]
        dists = (res.get("distances") or [[]])[0]
        for doc, meta, dist in zip(docs, metas, dists):
            score = 1.0 - float(dist) if dist is not None else 0.0
            if score < self.settings.rag_min_score:
                continue
            chunk_roles_raw = (meta or {}).get("roles", "public")
            chunk_roles: set[str] = set(chunk_roles_raw.split("|")) if chunk_roles_raw else {"public"}
            # Role check: caller must share at least one role with the chunk
            if roles and not roles.intersection(chunk_roles):
                continue
            out.append(
                RetrievedChunk(
                    file=(meta or {}).get("file", ""),
                    section_heading=(meta or {}).get("section_heading", ""),
                    tier=(meta or {}).get("tier", "public"),
                    roles=list(chunk_roles),
                    memory_type=(meta or {}).get("memory_type", "factual"),
                    score=score,
                    text=doc,
                    image_path=(meta or {}).get("image_path", ""),
                )
            )
            if len(out) >= self.settings.rag_top_k:
                break
        return out

    def context_block(self, chunks: list[RetrievedChunk]) -> str:
        """Render retrieved chunks into a single string injected after the system prompt."""
        if not chunks:
            return ""
        lines = ["# RETRIEVED CONTEXT", ""]
        for c in chunks:
            lines.append(f"## From {c.file} — {c.section_heading or '(intro)'} (score {c.score:.2f})")
            lines.append(c.text)
            # For image nodes, append a markdown image directive so the LLM can embed it.
            if c.image_path:
                lines.append(f"\n[Image available — to show it inline use: `![{c.section_heading or 'image'}](/api/content-image/{c.image_path})`]")
            lines.append("")
        return "\n".join(lines).rstrip() + "\n"


__all__ = ["RAGRetriever", "RetrievedChunk", "build_embedder"]
