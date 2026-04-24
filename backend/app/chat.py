"""/api/chat — SSE streaming endpoint."""

from __future__ import annotations

import json
import logging
import random
import time
from pathlib import Path
from typing import AsyncIterator, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from .auth import Caller, caller_dep
from .config import Settings, get_settings
from .logging_ import write_event
from .notify import fire as notify_fire
from .providers import LLMProvider, Message
from .rag import RAGRetriever
from .session import SessionState, store, TIER_LIMITS

log = logging.getLogger("ask-my-agent.chat")

router = APIRouter()

Role = Literal["user", "assistant"]


class ChatMessage(BaseModel):
    role: Role
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage]


async def _sse_stream(
    request: Request,
    body: ChatRequest,
    caller: Caller,
    session: SessionState,
    retriever: RAGRetriever,
    provider: LLMProvider,
    settings: Settings,
) -> AsyncIterator[dict]:
    """Yield SSE events: session, chunks_used, token, done, conversation_end, error."""
    started = time.time()
    try:
        yield {"event": "session", "data": json.dumps({
            "session_id": session.session_id,
            "tier": caller.tier,
            "turns_used": session.turns,
            "turn_limit": TIER_LIMITS[caller.tier][1],
        })}

        user_turns = [m.content for m in body.messages if m.role == "user"]
        chunks = retriever.retrieve(user_turns=user_turns, caller_roles=caller.roles)

        # Notify owner on Telegram for the first turn of each new conversation.
        # Skip for RFC 5737 TEST-NET IPs (192.0.2.x) used by the golden test harness.
        _is_test_ip = (caller.ip or "").startswith("192.0.2.")
        if session.turns == 1 and user_turns and not _is_test_ip:
            notify_fire(
                tier=caller.tier,
                ip_hash=caller.ip or "",
                first_message=user_turns[-1],
                bot_token=settings.telegram_bot_token,
                chat_id=settings.telegram_chat_id,
            )
        yield {"event": "chunks_used", "data": json.dumps([
            {"file": c.file, "section": c.section_heading, "score": round(c.score, 3), "tier": c.tier}
            for c in chunks
        ])}

        # System prompt from the knowledge DB
        system_text = request.app.state.knowledge.get_system_prompt() or ""
        context = retriever.context_block(chunks)
        full_system = system_text + ("\n\n" + context if context else "")

        history = [Message(role=m.role, content=m.content) for m in body.messages]

        full_text: list[str] = []
        final_meta: dict = {}
        first_token_time: float | None = None
        async for token, meta in provider.stream(system=full_system, messages=history):
            if await request.is_disconnected():
                break
            if token:
                if first_token_time is None:
                    first_token_time = time.time()
                full_text.append(token)
                yield {"event": "token", "data": token}
            if meta:
                final_meta = meta

        yield {"event": "done", "data": json.dumps({"ok": True})}

        # Emit conversation_end if we just hit the turn limit.
        limit = TIER_LIMITS[caller.tier][1]
        if limit > 0 and session.turns >= limit:
            store.close(session.session_id)
            yield {"event": "conversation_end", "data": json.dumps({
                "reason": "turn_limit",
                "message": "That's the end of this session. If you'd like to continue, start a new one.",
            })}

        # Log request metadata to NDJSON.
        log_event: dict = {
            "event": "chat",
            "session_id": session.session_id,
            "tier": caller.tier,
            "ip": caller.ip,
            "token": caller.token,
            "turn": session.turns,
            "ttft_ms": int((first_token_time - started) * 1000) if first_token_time else None,
            "latency_ms": int((time.time() - started) * 1000),
            "chunks": [
                {"file": c.file, "section": c.section_heading, "score": round(c.score, 3), "tier": c.tier}
                for c in chunks
            ],
            "response_chars": sum(len(t) for t in full_text),
            "response_preview": "".join(full_text)[:200],
            **final_meta,
        }
        # Store the user's first message so /whoasked can surface it.
        if session.turns == 1 and user_turns:
            log_event["user_message"] = user_turns[-1][:200]
        write_event(settings.log_path, log_event)
    except Exception as exc:  # noqa: BLE001
        log.exception("chat stream failed")
        write_event(settings.log_path, {
            "event": "chat_error",
            "session_id": session.session_id,
            "error": str(exc),
        })
        yield {"event": "error", "data": json.dumps({"message": "internal error"})}


@router.post("/api/chat")
async def chat(
    request: Request,
    body: ChatRequest,
    caller: Caller = Depends(caller_dep),
    x_session_id: str | None = Header(default=None, alias="X-Session-Id"),
):
    settings = get_settings()

    # Quota gates BEFORE starting the stream, so errors don't consume API credits.
    existing = store.get(x_session_id) if x_session_id else None
    if existing is None:
        ok, used, limit = store.check_conversation_quota(caller.tier, caller.ip, caller.token)
        if not ok:
            raise HTTPException(
                status_code=429,
                detail={"reason": "conversation_limit", "used": used, "limit": limit},
            )
    session = store.start_or_get(x_session_id, caller.ip, caller.token, caller.tier)

    if session.closed:
        raise HTTPException(status_code=409, detail={"reason": "session_closed"})

    turn_ok, turns_used, turn_max = store.check_turn_quota(caller.tier, session)
    if not turn_ok:
        raise HTTPException(
            status_code=429,
            detail={"reason": "turn_limit", "used": turns_used, "limit": turn_max},
        )

    # Count this turn now (we've already validated we can).
    store.bump_turn(session.session_id)
    session = store.get(session.session_id)  # refreshed

    retriever: RAGRetriever = request.app.state.retriever
    provider: LLMProvider = request.app.state.provider

    headers = {"X-Session-Id": session.session_id}
    return EventSourceResponse(
        _sse_stream(request, body, caller, session, retriever, provider, settings),
        headers=headers,
    )


# ── /api/suggestions ──────────────────────────────────────────────────────────

_QUESTION_TEMPLATES: dict[str, list[str]] = {
    "identity":    ["Who are you and what do you do?", "Give me a quick overview of who Sebastiaan is.", "What's your background in one paragraph?"],
    "experience":  ["Walk me through your career arc.", "What have you built in the last few years?", "Tell me about your work at {title}."],
    "project":     ["Tell me about the {title} project.", "What's the story behind {title}?", "How did the {title} project come about?"],
    "opinion":     ["What's your take on {title}?", "How do you think about {title}?", "Share your perspective on {title}."],
    "skill":       ["How do you use {title}?", "What's your approach to {title}?"],
    "education":   ["What's your educational background?", "How did your MBA shape how you think?"],
    "community":   ["What's your involvement in the AI community?", "Tell me about aiGrunn.", "What's aiGrunn Café?"],
    "personal":    ["What do you do outside of work?", "What's life like outside of AI?"],
    "faq":         ["What do people usually ask you first?", "What questions do you get the most?"],
}

_FALLBACK = [
    "Give me a quick summary of your career arc.",
    "What are your most interesting side projects?",
    "How do you think about AI and its role?",
    "What's your preferred tech stack and why?",
]


def _make_question(node_type: str, title: str) -> str:
    templates = _QUESTION_TEMPLATES.get(node_type, [])
    if not templates:
        return f"Tell me about {title}."
    t = random.choice(templates)
    return t.replace("{title}", title)


@router.get("/api/suggestions")
async def suggestions(request: Request):
    """Return 4 varied question chips drawn from knowledge nodes."""
    if not hasattr(request.app.state, "knowledge"):
        return {"suggestions": _FALLBACK}

    knowledge = request.app.state.knowledge
    nodes = knowledge.list_nodes(role_filter=["public", "recruiter"])

    if not nodes:
        return {"suggestions": _FALLBACK}

    # Bucket by type, then pick one node per bucket (up to 4), then sample more if needed
    by_type: dict[str, list] = {}
    for n in nodes:
        by_type.setdefault(n.type, []).append(n)

    picked = []
    # Prioritise variety: one per type
    type_order = ["identity", "experience", "project", "community", "opinion", "faq", "personal"]
    for t in type_order:
        if t in by_type and len(picked) < 4:
            node = random.choice(by_type[t])
            picked.append(_make_question(node.type, node.title))

    # Fill remaining slots from any remaining nodes
    remaining = [n for n in nodes if n not in picked]
    random.shuffle(remaining)
    for n in remaining:
        if len(picked) >= 4:
            break
        picked.append(_make_question(n.type, n.title))

    return {"suggestions": picked[:4]}


@router.get("/api/cv")
async def download_cv(settings: Settings = Depends(get_settings)) -> FileResponse:
    """Public endpoint: download Sebastiaan's CV as a PDF."""
    cv_path = settings.documents_path / "9de3bcbd.pdf"
    if not cv_path.exists():
        raise HTTPException(status_code=404, detail="CV not found")
    return FileResponse(
        path=str(cv_path),
        media_type="application/pdf",
        headers={"Content-Disposition": 'attachment; filename="Sebastiaan_den_Boer_CV.pdf"'},
    )


_DEFAULT_WELCOME = "Hey! I'm Sebastiaan's digital twin. Ask me about my experience, projects, or how I think about AI."
_DEFAULT_CHIPS = [
    {"label": "Career arc", "text": "Give me a quick summary of your career arc."},
    {"label": "Side projects", "text": "What are your most interesting side projects?"},
    {"label": "AI & data", "text": "How do you think about AI and its role?"},
    {"label": "Tech stack", "text": "What's your preferred tech stack and why?"},
]


@router.get("/api/content-config")
async def content_config(request: Request) -> dict:
    """Public endpoint — returns the current welcome message and suggestion chips."""
    if not hasattr(request.app.state, "knowledge"):
        return {"welcome_message": _DEFAULT_WELCOME, "chips": _DEFAULT_CHIPS}
    kb = request.app.state.knowledge
    welcome = kb.get_setting("welcome_message", _DEFAULT_WELCOME)
    chips_raw = kb.get_setting("suggestion_chips", None)
    chips = json.loads(chips_raw) if chips_raw else _DEFAULT_CHIPS
    return {"welcome_message": welcome, "chips": chips}
