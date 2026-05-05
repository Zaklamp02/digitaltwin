"""HTTP-level integration tests for /api/chat.

These tests exercise the full SSE pipeline against a lightweight in-process
app — no real LLM calls, no disk-backed ChromaDB shared between runs.

What is verified
----------------
* The ``session`` event carries the caller's resolved tier.
* The ``chunks_used`` event is emitted and contains document file references
  (the visible evidence that RAG is working).
* A public-tier caller never receives recruiter- or personal-tier chunks.
* A recruiter-tier caller cannot see personal-tier chunks.
* A personal-tier caller *can* receive personal-tier chunks.
* At least one ``token`` event is emitted and assembles into a non-empty reply.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.auth import Caller
from app.chat import router as chat_router
from app.config import Settings
from app.knowledge import KnowledgeDB
from app.providers import LLMProvider, Message
from app.rag import RAGRetriever
from app.session import SessionStore

# ── fake LLM provider ─────────────────────────────────────────────────────────


class FakeLLMProvider:
    """Yields a short, deterministic assistant reply without touching any API."""

    name = "fake"
    model = "fake-1"

    async def stream(
        self, system: str, messages: list[Message], max_tokens: int = 800
    ) -> AsyncIterator[tuple[str, dict]]:
        for word in ("Hello", " from", " the", " test", " provider."):
            yield word, {}
        yield "", {"provider": "fake", "model": "fake-1", "input_tokens": 10, "output_tokens": 5}


# ── fixture helpers ───────────────────────────────────────────────────────────


def _make_settings(tmp_vault_dir: Path, chroma_dir: Path, log_path: Path, tmp_path: Path) -> Settings:
    return Settings(
        llm_provider="openai",
        model_name="gpt-4o-mini",
        anthropic_api_key="x",
        openai_api_key="x",
        embedding_provider="openai",
        vault_dir=str(tmp_vault_dir),
        chroma_dir=str(chroma_dir),
        credentials_file=str(tmp_path / "credentials.yaml"),
        log_file=str(log_path),
        rag_top_k=5,
        rag_min_score=0.0,
        rag_context_turns=3,
        chunk_tokens=200,
        chunk_overlap=20,
    )


@pytest.fixture
def chat_app(tmp_vault_dir, tmp_knowledge_db, fake_embedder, isolated_chroma_dir, tmp_path, monkeypatch):
    """Minimal FastAPI app with the chat router, a test retriever, and a fake LLM.

    The real lifespan is bypassed; app.state is populated directly so tests
    stay fast and isolated.
    """
    settings = _make_settings(
        tmp_vault_dir, isolated_chroma_dir, tmp_path / "test_chat.ndjson", tmp_path
    )

    retriever = RAGRetriever(settings=settings, knowledge=tmp_knowledge_db, embedder=fake_embedder)
    retriever.reindex_all()

    import app.chat as chat_module

    # Patch get_settings so the chat router uses the temp log path.
    monkeypatch.setattr(chat_module, "get_settings", lambda: settings)
    # Isolate the session store so quota limits don't leak between tests.
    monkeypatch.setattr(chat_module, "store", SessionStore())

    application = FastAPI()
    application.include_router(chat_router)
    application.state.retriever = retriever
    application.state.provider = FakeLLMProvider()
    application.state.knowledge = tmp_knowledge_db

    return application


# ── SSE streaming helper ──────────────────────────────────────────────────────


async def _stream_events(
    application: FastAPI,
    caller: Caller,
    question: str,
) -> list[tuple[str, str]]:
    """POST /api/chat as *caller* and collect ``(event_name, data)`` pairs."""
    from app.auth import caller_dep

    application.dependency_overrides[caller_dep] = lambda: caller

    async with AsyncClient(
        transport=ASGITransport(app=application), base_url="http://test"
    ) as client:
        async with client.stream(
            "POST",
            "/api/chat",
            json={"messages": [{"role": "user", "content": question}]},
        ) as response:
            assert response.status_code == 200, (
                f"unexpected HTTP {response.status_code}"
            )
            events: list[tuple[str, str]] = []
            buf = ""
            async for chunk in response.aiter_text():
                # Normalise CRLF → LF so frame splitting always works.
                buf += chunk.replace("\r\n", "\n")
                while "\n\n" in buf:
                    frame, buf = buf.split("\n\n", 1)
                    evt = "message"
                    data_parts: list[str] = []
                    for line in frame.split("\n"):
                        if line.startswith("event:"):
                            evt = line[6:].strip()
                        elif line.startswith("data:"):
                            data_parts.append(line[5:].lstrip(" "))
                    if data_parts:
                        events.append((evt, "\n".join(data_parts)))
            return events


def _get_event(events: list[tuple[str, str]], name: str) -> dict | list | None:
    """Return the parsed JSON payload of the first event with *name*, or None."""
    for evt, data in events:
        if evt == name:
            try:
                return json.loads(data)
            except json.JSONDecodeError:
                return None
    return None


# ── tests — tier visibility ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_session_event_reports_public_tier(chat_app) -> None:
    """The ``session`` SSE event must report the caller's resolved tier (public)."""
    caller = Caller(token="", tier="public", roles=["public"], label="anon", ip="10.0.0.1")
    events = await _stream_events(chat_app, caller, "Who is Sebastiaan?")

    payload = _get_event(events, "session")
    assert payload is not None, "no session event received"
    assert payload["tier"] == "public", f"expected tier=public, got {payload['tier']}"


@pytest.mark.asyncio
async def test_session_event_reports_work_tier(chat_app) -> None:
    """The ``session`` SSE event must report the caller's resolved tier (work)."""
    caller = Caller(token="work-abc", tier="work", roles=["public", "work"], label="work", ip="10.0.0.2")
    events = await _stream_events(chat_app, caller, "What is he like as a person?")

    payload = _get_event(events, "session")
    assert payload is not None, "no session event received"
    assert payload["tier"] == "work", f"expected tier=work, got {payload['tier']}"


@pytest.mark.asyncio
async def test_session_event_reports_personal_tier(chat_app) -> None:
    """The ``session`` SSE event must report the caller's resolved tier (personal)."""
    caller = Caller(token="pers-xyz", tier="personal", roles=["public", "work", "friends", "personal"], label="inner circle", ip="10.0.0.3")
    events = await _stream_events(chat_app, caller, "Tell me everything.")

    payload = _get_event(events, "session")
    assert payload is not None, "no session event received"
    assert payload["tier"] == "personal", f"expected tier=personal, got {payload['tier']}"


# ── tests — document / chunk references ──────────────────────────────────────


@pytest.mark.asyncio
async def test_chunks_used_event_contains_document_file_references(chat_app) -> None:
    """``chunks_used`` must name the source files and tiers retrieved by RAG.

    This is the SSE event that proves documents are actually being fetched and
    surfaced — visible in the test output as file paths and tier labels.
    """
    caller = Caller(token="", tier="public", roles=["public"], label="anon", ip="10.0.0.4")
    events = await _stream_events(chat_app, caller, "Utrecht AI practice founded")

    chunks = _get_event(events, "chunks_used")
    assert chunks is not None, "no chunks_used event received"
    assert isinstance(chunks, list) and len(chunks) > 0, (
        "expected at least one retrieved chunk in chunks_used"
    )
    for chunk in chunks:
        assert "file" in chunk, f"chunk is missing 'file' key: {chunk}"
        assert "tier" in chunk, f"chunk is missing 'tier' key: {chunk}"
        assert "score" in chunk, f"chunk is missing 'score' key: {chunk}"

    files = {c["file"] for c in chunks}
    tiers = {c["tier"] for c in chunks}
    # Surface the retrieved documents in the test output for traceability.
    print(f"\n  retrieved documents: {sorted(files)}")
    print(f"  tiers represented:   {sorted(tiers)}")

    assert any("public_bio" in f for f in files), (
        f"expected public_bio.md among retrieved docs; got: {sorted(files)}"
    )


# ── tests — access-control isolation ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_public_caller_chunks_contain_only_public_tier(chat_app) -> None:
    """A public-tier caller must never receive work- or personal-tier chunks."""
    caller = Caller(token="", tier="public", roles=["public"], label="anon", ip="10.0.1.1")
    events = await _stream_events(chat_app, caller, "Who is Sebastiaan?")

    chunks = _get_event(events, "chunks_used")
    assert chunks is not None, "no chunks_used event received"
    non_public = [c for c in chunks if c.get("tier") != "public"]
    assert non_public == [], (
        f"public caller received non-public chunks: {non_public}"
    )


@pytest.mark.asyncio
async def test_work_caller_cannot_see_personal_chunks(chat_app) -> None:
    """A work-tier caller must not receive personal-tier chunks."""
    caller = Caller(token="work-abc", tier="work", roles=["public", "work"], label="work", ip="10.0.1.2")
    events = await _stream_events(
        chat_app, caller, "Tell me about his personal anecdotes from Youwe"
    )

    chunks = _get_event(events, "chunks_used")
    assert chunks is not None, "no chunks_used event received"
    personal_chunks = [c for c in chunks if c.get("tier") == "personal"]
    assert personal_chunks == [], (
        f"work caller received personal chunks: {personal_chunks}"
    )


@pytest.mark.asyncio
async def test_personal_caller_can_receive_personal_chunks(chat_app) -> None:
    """A personal-tier caller must be able to retrieve personal-tier documents."""
    caller = Caller(token="pers-xyz", tier="personal", roles=["public", "work", "friends", "personal"], label="inner circle", ip="10.0.1.3")
    events = await _stream_events(
        chat_app, caller, "First week at Youwe inner circle story"
    )

    chunks = _get_event(events, "chunks_used")
    assert chunks is not None, "no chunks_used event received"
    tiers = {c.get("tier") for c in chunks}
    print(f"\n  chunks returned to personal caller — tiers: {sorted(tiers)}")
    assert "personal" in tiers, (
        f"personal caller should see personal chunks; got tiers: {sorted(tiers)}"
    )


# ── tests — streaming mechanics ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_token_events_assemble_into_non_empty_reply(chat_app) -> None:
    """At least one ``token`` event must be emitted and produce a non-empty reply."""
    caller = Caller(token="", tier="public", roles=["public"], label="anon", ip="10.0.2.1")
    events = await _stream_events(chat_app, caller, "Hello")

    token_events = [data for evt, data in events if evt == "token"]
    assert token_events, "expected at least one token event in SSE stream"
    full_reply = "".join(token_events)
    assert len(full_reply) > 0, "assembled reply from token events is empty"
    print(f"\n  assembled reply: {full_reply!r}")
