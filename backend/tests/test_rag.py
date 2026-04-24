"""RAG layer tests — chunking, role filtering, contextual queries."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.config import Settings
from app.indexer import chunk_node
from app.knowledge import KnowledgeDB
from app.rag import RAGRetriever


def _make_settings(tmp_memory_dir: Path, chroma_dir: Path, isolated: Path) -> Settings:
    return Settings(
        llm_provider="openai",
        model_name="gpt-4o-mini",
        anthropic_api_key="x",
        openai_api_key="x",
        embedding_provider="openai",
        memory_dir=str(tmp_memory_dir),
        chroma_dir=str(isolated),
        credentials_file=str(tmp_memory_dir / "credentials.yaml"),
        rag_top_k=5,
        rag_min_score=0.0,  # relaxed for the fake embedder
        rag_context_turns=3,
        chunk_tokens=200,
        chunk_overlap=20,
    )


def test_chunking_splits_by_headings(tmp_knowledge_db: KnowledgeDB) -> None:
    for node in tmp_knowledge_db.list_nodes():
        if node.type == "system":
            continue
        chunks = chunk_node(node, chunk_tokens=200, overlap=20)
        assert chunks, f"expected at least one chunk for node {node.id}"
        assert all(c.file == f"node:{node.id}" for c in chunks)


def test_contextual_query_takes_last_n_turns() -> None:
    q = RAGRetriever.contextual_query(
        user_turns=["first turn", "second turn", "third turn", "fourth turn"],
        n=3,
    )
    assert q == "second turn\nthird turn\nfourth turn"


def test_role_filter_excludes_higher_roles(
    tmp_memory_dir: Path, tmp_path: Path, fake_embedder, isolated_chroma_dir: Path,
    tmp_knowledge_db: KnowledgeDB,
) -> None:
    settings = _make_settings(tmp_memory_dir, tmp_path / "c", isolated_chroma_dir)
    retriever = RAGRetriever(settings=settings, knowledge=tmp_knowledge_db, embedder=fake_embedder)
    retriever.reindex_all()

    # public caller — role filtering uses intersection of caller roles and chunk roles
    pub = retriever.retrieve(user_turns=["tell me about Sebastiaan"], caller_roles=["public"])
    assert pub, "public retrieval returned nothing"
    # All returned chunks must share at least one role with the caller
    for c in pub:
        assert "public" in c.roles, f"chunk {c.file} lacks 'public' role: {c.roles}"

    # recruiter caller can see public + recruiter but not personal
    rec = retriever.retrieve(
        user_turns=["what's he like as a person"],
        caller_roles=["public", "recruiter"],
    )
    assert rec, "recruiter retrieval returned nothing"
    for c in rec:
        assert set(c.roles) & {"public", "recruiter"}, f"recruiter chunk has no matching role: {c.roles}"
    assert not any(c.tier == "personal" for c in rec)

    # personal caller can see everything
    pers = retriever.retrieve(
        user_turns=["first week at Youwe"],
        caller_roles=["public", "recruiter", "personal"],
    )
    assert any(c.tier == "personal" for c in pers)


def test_context_block_renders_when_chunks_present(
    tmp_memory_dir: Path, tmp_path: Path, fake_embedder, isolated_chroma_dir: Path,
    tmp_knowledge_db: KnowledgeDB,
) -> None:
    settings = _make_settings(tmp_memory_dir, tmp_path / "c", isolated_chroma_dir)
    retriever = RAGRetriever(settings=settings, knowledge=tmp_knowledge_db, embedder=fake_embedder)
    retriever.reindex_all()
    chunks = retriever.retrieve(
        user_turns=["Utrecht AI practice founded"], caller_roles=["public"]
    )
    block = retriever.context_block(chunks)
    assert "# RETRIEVED CONTEXT" in block
    assert "node:public_bio" in block


def test_empty_context_block_when_no_chunks(
    tmp_memory_dir: Path, tmp_path: Path, fake_embedder, isolated_chroma_dir: Path,
    tmp_knowledge_db: KnowledgeDB,
) -> None:
    settings = _make_settings(tmp_memory_dir, tmp_path / "c", isolated_chroma_dir)
    retriever = RAGRetriever(
        settings=settings,
        knowledge=tmp_knowledge_db,
        embedder=fake_embedder,
    )
    assert retriever.context_block([]) == ""
