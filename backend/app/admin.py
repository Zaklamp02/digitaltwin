"""Admin API — personal-tier only.

All routes require the caller to hold a personal-tier token.
Exposes: stats, raw log viewer, memory explorer (read/write/delete),
runtime config (model selection, RAG params), active session list,
and RBAC roles + token management.
"""
from __future__ import annotations

import hashlib
import json
import logging
import secrets
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, AsyncIterator

import uuid

import yaml
import httpx
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from .auth import Caller, caller_dep
from .config import get_settings, load_role_definitions, load_tokens, save_credentials
from .session import TIER_LIMITS, store

log = logging.getLogger("ask-my-agent.admin")

router = APIRouter(prefix="/api/admin")

# ── auth guard ────────────────────────────────────────────────────────────────


def _personal(caller: Caller = Depends(caller_dep)) -> Caller:
    if caller.tier != "personal":
        raise HTTPException(
            status_code=403,
            detail="Admin access requires a personal-tier token.",
        )
    return caller


# ── log helpers ───────────────────────────────────────────────────────────────


def _read_log(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return out


def _day(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d")


# ── stats ─────────────────────────────────────────────────────────────────────


@router.get("/stats")
async def get_stats(
    request: Request,
    caller: Caller = Depends(_personal),
) -> dict[str, Any]:
    settings = get_settings()
    entries = _read_log(settings.log_path)
    chats = [e for e in entries if e.get("event") == "chat"]

    now = datetime.now(timezone.utc)
    week_ago = now - timedelta(days=7)

    sessions_today: set[str] = set()
    sessions_week: set[str] = set()
    sessions_total: set[str] = set()
    tier_by_conv: dict[str, str] = {}  # session_id → tier (first seen)
    turns_today = 0
    in_today = out_today = in_total = out_total = 0
    latencies: list[int] = []
    ttft_latencies: list[int] = []
    timeline: dict[str, set[str]] = defaultdict(set)
    model_counts: dict[str, int] = defaultdict(int)
    turns_per_session: dict[str, int] = defaultdict(int)

    for e in chats:
        ts_raw = e.get("ts", "")
        try:
            ts = datetime.fromisoformat(ts_raw)
        except Exception:
            continue

        sid = e.get("session_id", "?")
        tier = e.get("tier", "public")
        d = _day(ts)

        sessions_total.add(sid)
        timeline[d].add(sid)
        turns_per_session[sid] += 1
        if sid not in tier_by_conv:
            tier_by_conv[sid] = tier

        in_total += e.get("input_tokens") or 0
        out_total += e.get("output_tokens") or 0

        if ts.date() == now.date():
            sessions_today.add(sid)
            turns_today += 1
            in_today += e.get("input_tokens") or 0
            out_today += e.get("output_tokens") or 0

        if ts >= week_ago:
            sessions_week.add(sid)

        lat = e.get("latency_ms")
        if isinstance(lat, int):
            latencies.append(lat)

        ttft = e.get("ttft_ms")
        if isinstance(ttft, int):
            ttft_latencies.append(ttft)

        model = e.get("model", "unknown")
        model_counts[model] += 1

    # tier breakdown — count unique conversations per tier
    tier_breakdown: dict[str, int] = defaultdict(int)
    for sid, tier in tier_by_conv.items():
        tier_breakdown[tier] += 1

    avg_turns = (
        sum(turns_per_session.values()) / len(turns_per_session)
        if turns_per_session else 0.0
    )

    avg_lat = int(sum(latencies) / len(latencies)) if latencies else 0
    sorted_lat = sorted(latencies)
    p95_lat = sorted_lat[int(len(sorted_lat) * 0.95)] if sorted_lat else 0

    avg_ttft = int(sum(ttft_latencies) / len(ttft_latencies)) if ttft_latencies else 0
    sorted_ttft = sorted(ttft_latencies)
    p95_ttft = sorted_ttft[int(len(sorted_ttft) * 0.95)] if sorted_ttft else 0

    # rough cost: $2/M input, $8/M output (conservative across providers)
    cost_usd = (in_total / 1_000_000 * 2.0) + (out_total / 1_000_000 * 8.0)

    # 30-day conversation timeline
    timeline_out = []
    for i in range(30):
        d = now - timedelta(days=29 - i)
        ds = _day(d)
        timeline_out.append({"date": ds, "conversations": len(timeline.get(ds, set()))})

    return {
        "conversations_today": len(sessions_today),
        "conversations_week": len(sessions_week),
        "conversations_total": len(sessions_total),
        "turns_today": turns_today,
        "avg_turns_per_conversation": round(avg_turns, 1),
        "tier_breakdown": dict(tier_breakdown),
        "token_input_today": in_today,
        "token_output_today": out_today,
        "token_input_total": in_total,
        "token_output_total": out_total,
        "cost_estimate_usd": round(cost_usd, 4),
        "avg_latency_ms": avg_lat,
        "p95_latency_ms": p95_lat,
        "avg_ttft_ms": avg_ttft,
        "p95_ttft_ms": p95_ttft,
        "timeline": timeline_out,
        "model_breakdown": dict(model_counts),
    }


# ── raw log viewer ────────────────────────────────────────────────────────────


@router.get("/logs")
async def get_logs(
    request: Request,
    limit: int = 50,
    offset: int = 0,
    caller: Caller = Depends(_personal),
) -> dict[str, Any]:
    settings = get_settings()
    entries = list(reversed(_read_log(settings.log_path)))
    total = len(entries)
    page = entries[offset : offset + limit]
    return {"total": total, "offset": offset, "limit": limit, "entries": page}


# ── config ────────────────────────────────────────────────────────────────────


ALLOWED_MODELS: dict[str, list[str]] = {
    "anthropic": [
        "claude-opus-4-5",
        "claude-sonnet-4-6",
        "claude-haiku-3-5",
        "claude-3-5-sonnet-20241022",
        "claude-3-5-haiku-20241022",
    ],
    "openai": [
        "gpt-5.4",
        "gpt-5.4-mini",
        "gpt-5.4-nano",
        "gpt-4.1",
        "gpt-4.1-mini",
        "gpt-4.1-nano",
        "gpt-4o",
        "gpt-4o-mini",
        "gpt-4-turbo",
        "gpt-3.5-turbo",
        "o1-mini",
    ],
}


async def _fetch_ollama_models(base_url: str) -> list[str]:
    """Query the running Ollama instance for installed models."""
    try:
        url = f"{base_url.rstrip('/')}/api/tags"
        async with httpx.AsyncClient(timeout=3) as client:
            r = await client.get(url)
            r.raise_for_status()
            data = r.json()
            return [m["name"] for m in data.get("models", [])]
    except Exception as exc:  # noqa: BLE001
        log.warning("could not fetch ollama models: %s", exc)
        return []

# Voices supported by gpt-4o-mini-tts (all 13)
TTS_VOICES_ALL = ["alloy", "ash", "ballad", "coral", "echo", "fable", "nova", "onyx", "sage", "shimmer", "verse", "marin", "cedar"]
# Voices supported by tts-1 / tts-1-hd (9)
TTS_VOICES_BASIC = ["alloy", "ash", "coral", "echo", "fable", "onyx", "nova", "sage", "shimmer"]
# Keep for backward compatibility
TTS_VOICES = TTS_VOICES_ALL

TTS_MODELS = ["tts-1", "tts-1-hd", "gpt-4o-mini-tts"]
STT_MODELS = ["whisper-1", "gpt-4o-mini-transcribe", "gpt-4o-transcribe"]


@router.get("/config")
async def get_config(
    request: Request,
    caller: Caller = Depends(_personal),
) -> dict[str, Any]:
    settings = get_settings()
    provider = request.app.state.provider
    allowed = dict(ALLOWED_MODELS)
    # Always include live Ollama model list so the UI can show it regardless of current provider
    allowed["ollama"] = await _fetch_ollama_models(settings.ollama_base_url)
    return {
        "llm_provider": settings.llm_provider,
        "model_name": provider.model,
        "embedding_provider": settings.embedding_provider,
        "embedding_model": settings.embedding_model,
        "rag_top_k": settings.rag_top_k,
        "rag_min_score": settings.rag_min_score,
        "rag_context_turns": settings.rag_context_turns,
        "chunk_tokens": settings.chunk_tokens,
        "chunk_overlap": settings.chunk_overlap,
        "tts_model": settings.tts_model,
        "tts_voice": settings.tts_voice,
        "stt_model": settings.stt_model,
        "rate_limit_enabled": settings.rate_limit_enabled,
        "allowed_models": allowed,
        "tts_models": TTS_MODELS,
        "stt_models": STT_MODELS,
        "tts_voices": TTS_VOICES_ALL,
        "tts_voices_all": TTS_VOICES_ALL,
        "tts_voices_basic": TTS_VOICES_BASIC,
        "tier_limits": {
            tier: {
                "conversations_per_day": lims[0],
                "turns_per_conversation": lims[1],
            }
            for tier, lims in TIER_LIMITS.items()
        },
    }


class ConfigPatchBody(BaseModel):
    llm_provider: str | None = None
    model_name: str | None = None
    rag_top_k: int | None = None
    rag_min_score: float | None = None
    rate_limit_enabled: bool | None = None
    tts_model: str | None = None
    tts_voice: str | None = None
    stt_model: str | None = None


@router.patch("/config")
async def patch_config(
    body: ConfigPatchBody,
    request: Request,
    caller: Caller = Depends(_personal),
) -> dict[str, Any]:
    from .providers import AnthropicProvider, OllamaProvider, OpenAIProvider

    settings = get_settings()
    changed: list[str] = []

    if body.llm_provider is not None:
        allowed_providers = ["anthropic", "openai", "ollama"]
        if body.llm_provider not in allowed_providers:
            raise HTTPException(status_code=400, detail=f"Unknown provider: {body.llm_provider}")
        settings.llm_provider = body.llm_provider  # type: ignore[assignment]
        changed.append(f"llm_provider={body.llm_provider}")
        log.info("admin switched provider to %s", body.llm_provider)

    if body.model_name is not None:
        allowed = ALLOWED_MODELS.get(settings.llm_provider, [])
        # For Ollama, accept any model name (validated against the live list would
        # require an async call here; we trust the admin knows what they installed).
        if settings.llm_provider != "ollama" and body.model_name not in allowed:
            raise HTTPException(
                status_code=400,
                detail=f"Model not in allowed list for provider '{settings.llm_provider}': {allowed}",
            )
        if settings.llm_provider == "anthropic":
            request.app.state.provider = AnthropicProvider(
                api_key=settings.anthropic_api_key, model=body.model_name
            )
        elif settings.llm_provider == "ollama":
            request.app.state.provider = OllamaProvider(
                base_url=settings.ollama_base_url, model=body.model_name
            )
        else:
            request.app.state.provider = OpenAIProvider(
                api_key=settings.openai_api_key, model=body.model_name
            )
        changed.append(f"model_name={body.model_name}")

    if body.rag_top_k is not None:
        settings.rag_top_k = body.rag_top_k
        changed.append(f"rag_top_k={body.rag_top_k}")

    if body.rag_min_score is not None:
        settings.rag_min_score = body.rag_min_score
        changed.append(f"rag_min_score={body.rag_min_score}")

    if body.rate_limit_enabled is not None:
        settings.rate_limit_enabled = body.rate_limit_enabled
        changed.append(f"rate_limit_enabled={body.rate_limit_enabled}")

    if body.tts_model is not None:
        if body.tts_model not in TTS_MODELS:
            raise HTTPException(status_code=400, detail=f"Unknown TTS model: {body.tts_model}")
        settings.tts_model = body.tts_model
        changed.append(f"tts_model={body.tts_model}")

    if body.tts_voice is not None:
        allowed_voices = TTS_VOICES_ALL if settings.tts_model == "gpt-4o-mini-tts" else TTS_VOICES_BASIC
        if body.tts_voice not in allowed_voices:
            raise HTTPException(status_code=400, detail=f"Unknown voice for model '{settings.tts_model}': {body.tts_voice}")
        settings.tts_voice = body.tts_voice
        changed.append(f"tts_voice={body.tts_voice}")

    if body.stt_model is not None:
        if body.stt_model not in STT_MODELS:
            raise HTTPException(status_code=400, detail=f"Unknown STT model: {body.stt_model}")
        settings.stt_model = body.stt_model
        changed.append(f"stt_model={body.stt_model}")

    log.info("admin config patch: %s", ", ".join(changed))
    return {"ok": True, "changed": changed}


# ── content configuration ────────────────────────────────────────────────────

_DEFAULT_WELCOME = "Hey! I'm Sebastiaan's digital twin. Ask me about my experience, projects, or how I think about AI."
_DEFAULT_CHIPS: list[dict[str, str]] = [
    {"label": "Career arc", "text": "Give me a quick summary of your career arc."},
    {"label": "Side projects", "text": "What are your most interesting side projects?"},
    {"label": "AI & data", "text": "How do you think about AI and its role?"},
    {"label": "Tech stack", "text": "What's your preferred tech stack and why?"},
]


def _get_content_config(kb, request) -> dict[str, Any]:
    welcome = kb.get_setting("welcome_message", _DEFAULT_WELCOME)
    chips_raw = kb.get_setting("suggestion_chips", None)
    chips = json.loads(chips_raw) if chips_raw else _DEFAULT_CHIPS
    # System prompt from the knowledge DB
    system_prompt = kb.get_system_prompt() or ""
    return {"welcome_message": welcome, "system_prompt": system_prompt, "chips": chips}


@router.get("/content")
async def get_content_config(
    request: Request,
    caller: Caller = Depends(_personal),
) -> dict[str, Any]:
    """Return the current content configuration."""
    kb = request.app.state.knowledge
    return _get_content_config(kb, request)


class ContentPatchBody(BaseModel):
    welcome_message: str | None = None
    system_prompt: str | None = None
    chips: list[dict[str, str]] | None = None


@router.patch("/content")
async def patch_content_config(
    body: ContentPatchBody,
    request: Request,
    caller: Caller = Depends(_personal),
) -> dict[str, Any]:
    """Update welcome message, system prompt and/or suggestion chips."""
    kb = request.app.state.knowledge
    changed: list[str] = []

    if body.welcome_message is not None:
        kb.set_setting("welcome_message", body.welcome_message)
        changed.append("welcome_message")

    if body.system_prompt is not None:
        # Write to _system.md (source of truth) AND upsert into DB as system node
        settings = get_settings()
        system_path = settings.memory_path / "_system.md"
        system_path.write_text(f"<!-- tier: system -->\n{body.system_prompt}", encoding="utf-8")
        # Also update or create the system node in the DB
        now = kb._now()
        with kb._lock, kb._conn:
            kb._conn.execute(
                "INSERT INTO nodes (id, type, title, body, metadata, roles, created_at, updated_at)"
                " VALUES ('_system', 'system', 'System Prompt', ?, '{}', '[\"public\"]', ?, ?)"
                " ON CONFLICT(id) DO UPDATE SET body = excluded.body, updated_at = excluded.updated_at",
                (body.system_prompt, now, now),
            )
        changed.append("system_prompt")

    if body.chips is not None:
        kb.set_setting("suggestion_chips", json.dumps(body.chips))
        changed.append("chips")

    log.info("content config updated: %s", ", ".join(changed))
    return {"ok": True, "changed": changed}


# ── roles & tokens ───────────────────────────────────────────────────────────

BUILTIN_ROLES = {"public", "work", "friends", "personal"}


@router.get("/roles")
async def get_roles(
    request: Request,
    caller: Caller = Depends(_personal),
) -> dict[str, Any]:
    settings = get_settings()
    role_defs = load_role_definitions(settings.credentials_path)
    tokens = load_tokens(settings.credentials_path)
    # Count tokens per role
    role_token_count: dict[str, int] = defaultdict(int)
    for meta in tokens.values():
        for r in meta.get("roles", []):
            role_token_count[r] += 1
    for rd in role_defs:
        rd["token_count"] = role_token_count.get(rd["name"], 0)
        rd["builtin"] = rd["name"] in BUILTIN_ROLES
    return {"roles": role_defs}


class RoleCreateBody(BaseModel):
    name: str
    description: str = ""


@router.post("/roles")
async def create_role(
    body: RoleCreateBody,
    request: Request,
    caller: Caller = Depends(_personal),
) -> dict[str, Any]:
    settings = get_settings()
    if not body.name or not body.name.replace("-", "").replace("_", "").isalnum():
        raise HTTPException(status_code=400, detail="Role name must be alphanumeric (hyphens/underscores ok)")
    if body.name in BUILTIN_ROLES:
        raise HTTPException(status_code=400, detail="Cannot override built-in role")
    creds_path = settings.credentials_path
    if creds_path.exists():
        with creds_path.open() as f:
            data = yaml.safe_load(f) or {}
    else:
        data = {}
    roles_list = data.get("roles") or []
    if any(r.get("name") == body.name for r in roles_list):
        raise HTTPException(status_code=409, detail="Role already exists")
    roles_list.append({"name": body.name, "description": body.description})
    data["roles"] = roles_list
    save_credentials(creds_path, data)
    return {"ok": True, "name": body.name}


@router.delete("/roles/{name}")
async def delete_role(
    name: str,
    request: Request,
    caller: Caller = Depends(_personal),
) -> dict[str, Any]:
    if name in BUILTIN_ROLES:
        raise HTTPException(status_code=403, detail="Cannot delete built-in roles")
    settings = get_settings()
    creds_path = settings.credentials_path
    if not creds_path.exists():
        raise HTTPException(status_code=404, detail="No credentials.yaml found")
    with creds_path.open() as f:
        data = yaml.safe_load(f) or {}
    roles_list = [r for r in (data.get("roles") or []) if r.get("name") != name]
    data["roles"] = roles_list
    save_credentials(creds_path, data)
    return {"ok": True}


@router.get("/tokens")
async def get_tokens(
    request: Request,
    caller: Caller = Depends(_personal),
) -> dict[str, Any]:
    settings = get_settings()
    tokens = load_tokens(settings.credentials_path)
    result = []
    for token, meta in tokens.items():
        result.append({
            "token": token or "(empty — public)",
            "token_raw": token,
            "roles": meta.get("roles", ["public"]),
            "tier": meta.get("tier", "public"),
            "label": meta.get("label", ""),
            "is_empty": token == "",
        })
    result.sort(key=lambda t: (t["tier"], t["label"]))
    return {"tokens": result}


class TokenCreateBody(BaseModel):
    label: str
    roles: list[str]


@router.post("/tokens")
async def create_token(
    body: TokenCreateBody,
    request: Request,
    caller: Caller = Depends(_personal),
) -> dict[str, Any]:
    if not body.roles:
        raise HTTPException(status_code=400, detail="At least one role required")
    settings = get_settings()
    creds_path = settings.credentials_path
    if creds_path.exists():
        with creds_path.open() as f:
            data = yaml.safe_load(f) or {}
    else:
        data = {"tokens": {}}
    tokens_dict = data.get("tokens") or {}
    new_token = secrets.token_urlsafe(8)
    # Derive prefix from highest-privilege role
    if "personal" in body.roles:
        prefix = "pers"
    elif "friends" in body.roles:
        prefix = "fr"
    elif "work" in body.roles:
        prefix = "work"
    else:
        prefix = "pub"
    token_key = f"{prefix}-{new_token}"
    tokens_dict[token_key] = {"roles": body.roles, "label": body.label}
    data["tokens"] = tokens_dict
    save_credentials(creds_path, data)
    return {"ok": True, "token": token_key, "label": body.label}


@router.delete("/tokens/{token_key:path}")
async def revoke_token(
    token_key: str,
    request: Request,
    caller: Caller = Depends(_personal),
) -> dict[str, Any]:
    if token_key == "" or token_key == "(empty — public)":
        raise HTTPException(status_code=403, detail="Cannot revoke the anonymous public token")
    # Also check if this is the caller's own token (prevent self-lockout)
    if token_key == caller.token:
        raise HTTPException(status_code=403, detail="Cannot revoke your own active token")
    settings = get_settings()
    creds_path = settings.credentials_path
    if not creds_path.exists():
        raise HTTPException(status_code=404)
    with creds_path.open() as f:
        data = yaml.safe_load(f) or {}
    tokens_dict = data.get("tokens") or {}
    if token_key not in tokens_dict:
        raise HTTPException(status_code=404, detail="Token not found")
    del tokens_dict[token_key]
    data["tokens"] = tokens_dict
    save_credentials(creds_path, data)
    return {"ok": True}


# ── sessions ──────────────────────────────────────────────────────────────────


@router.get("/sessions")
async def get_sessions(
    request: Request,
    caller: Caller = Depends(_personal),
) -> dict[str, Any]:
    now = time.time()
    sessions = []
    for sid, state in store._sessions.items():
        sessions.append(
            {
                "session_id": sid,
                "tier": state.tier,
                # One-way hash of IP to avoid logging raw addresses in the UI
                "ip_hash": hashlib.sha256(state.ip.encode()).hexdigest()[:12],
                "turns": state.turns,
                "closed": state.closed,
                "started_ago_s": int(now - state.started_at),
            }
        )
    sessions.sort(key=lambda s: s["started_ago_s"])
    return {"sessions": sessions}


# ── knowledge graph ───────────────────────────────────────────────────────────


def _knowledge(request: Request):
    """Helper: get KnowledgeDB from app state or raise 503."""
    kb = getattr(request.app.state, "knowledge", None)
    if kb is None:
        raise HTTPException(status_code=503, detail="Knowledge DB not available")
    return kb


@router.get("/nodes/orphans")
async def list_orphan_nodes(
    request: Request,
    caller: Caller = Depends(_personal),
) -> dict[str, Any]:
    """Return nodes not reachable from any notebook root via containment edges."""
    from .knowledge import CONTAINMENT_EDGE_TYPES

    kb = _knowledge(request)
    nodes = kb.list_nodes()
    edges = kb.list_edges()

    # Find notebook roots
    notebook_roots = [n.id for n in nodes if n.metadata.get("notebook_root")]

    # BFS from all notebook roots via containment edges
    in_notebooks: set[str] = set(notebook_roots)
    stack = list(notebook_roots)
    edge_map: dict[str, list[str]] = {}  # parent → children
    for e in edges:
        if e.type not in CONTAINMENT_EDGE_TYPES:
            continue
        if e.type in ("member_of", "studied_at"):
            parent, child = e.target_id, e.source_id
        else:
            parent, child = e.source_id, e.target_id
        edge_map.setdefault(parent, []).append(child)
    while stack:
        nid = stack.pop()
        for child in edge_map.get(nid, []):
            if child not in in_notebooks:
                in_notebooks.add(child)
                stack.append(child)

    orphans = [
        n for n in nodes
        if n.id not in in_notebooks and n.type not in ("system", "notebook")
    ]
    return {
        "nodes": [
            {
                "id": n.id,
                "type": n.type,
                "title": n.title,
                "roles": n.roles,
                "body_preview": n.body[:200] if n.body else "",
                "updated_at": n.updated_at,
                "created_at": n.created_at,
            }
            for n in orphans
        ]
    }


@router.get("/nodes")
async def list_nodes(
    request: Request,
    type: str | None = None,
    search: str | None = None,
    caller: Caller = Depends(_personal),
) -> dict[str, Any]:
    kb = _knowledge(request)
    if search:
        nodes = kb.search_nodes(search)
        if type:
            nodes = [n for n in nodes if n.type == type]
    else:
        nodes = kb.list_nodes(type_filter=type)
    return {
        "nodes": [
            {
                "id": n.id,
                "type": n.type,
                "title": n.title,
                "roles": n.roles,
                "body_preview": n.body[:200] if n.body else "",
                "updated_at": n.updated_at,
                "created_at": n.created_at,
            }
            for n in nodes
        ]
    }


@router.get("/nodes/{node_id}")
async def get_node(
    node_id: str,
    request: Request,
    caller: Caller = Depends(_personal),
) -> dict[str, Any]:
    kb = _knowledge(request)
    node = kb.get_node(node_id)
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    edges = kb.get_edges_for_node(node_id)
    # Enrich edges with the other node's title
    enriched_edges = []
    for e in edges:
        other_id = e.target_id if e.source_id == node_id else e.source_id
        other = kb.get_node(other_id)
        enriched_edges.append({
            "id": e.id,
            "source_id": e.source_id,
            "target_id": e.target_id,
            "type": e.type,
            "label": e.label,
            "roles": e.roles,
            "direction": "outgoing" if e.source_id == node_id else "incoming",
            "other_title": other.title if other else other_id,
            "other_type": other.type if other else "unknown",
        })
    return {
        "id": node.id,
        "type": node.type,
        "title": node.title,
        "body": node.body,
        "roles": node.roles,
        "metadata": node.metadata,
        "created_at": node.created_at,
        "updated_at": node.updated_at,
        "edges": enriched_edges,
    }


class NodeCreateBody(BaseModel):
    type: str
    title: str
    body: str = ""
    roles: list[str] = ["public"]
    metadata: dict[str, Any] = {}


@router.post("/nodes")
async def create_node(
    body: NodeCreateBody,
    request: Request,
    caller: Caller = Depends(_personal),
) -> dict[str, Any]:
    from .knowledge import NODE_TYPES
    if body.type not in NODE_TYPES:
        raise HTTPException(status_code=400, detail=f"Unknown type. Valid: {NODE_TYPES}")
    kb = _knowledge(request)
    node = kb.create_node(
        type=body.type,
        title=body.title,
        body=body.body,
        roles=body.roles,
        metadata=body.metadata,
    )
    # Trigger re-index for the new node
    retriever = getattr(request.app.state, "retriever", None)
    if retriever is not None and node.type != "system":
        retriever.reindex_node(node)
    return {"ok": True, "id": node.id}


class NodeUpdateBody(BaseModel):
    type: str | None = None
    title: str | None = None
    body: str | None = None
    roles: list[str] | None = None
    metadata: dict[str, Any] | None = None


@router.put("/nodes/{node_id}")
async def update_node(
    node_id: str,
    body: NodeUpdateBody,
    request: Request,
    caller: Caller = Depends(_personal),
) -> dict[str, Any]:
    kb = _knowledge(request)
    kwargs = {k: v for k, v in body.model_dump().items() if v is not None}
    node = kb.update_node(node_id, **kwargs)
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    retriever = getattr(request.app.state, "retriever", None)
    if retriever is not None and node.type != "system":
        retriever.reindex_node(node)
    return {"ok": True, "id": node.id, "updated_at": node.updated_at}


@router.delete("/nodes/{node_id}")
async def delete_node(
    node_id: str,
    request: Request,
    caller: Caller = Depends(_personal),
) -> dict[str, Any]:
    kb = _knowledge(request)
    node = kb.get_node(node_id)
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    retriever = getattr(request.app.state, "retriever", None)
    if retriever is not None:
        retriever.delete_node_from_index(node_id)
    # Clean up any attached document file
    if node.type == "document" and node.metadata.get("file_path"):
        settings = get_settings()
        file_rel = Path(node.metadata["file_path"])
        if not file_rel.is_absolute() and ".." not in file_rel.parts:
            file_abs = settings.documents_path.parent / file_rel
            try:
                file_abs.unlink(missing_ok=True)
            except Exception as exc:  # noqa: BLE001
                log.warning("could not delete document file %s: %s", file_abs, exc)
    kb.delete_node(node_id)
    return {"ok": True}


@router.get("/edges")
async def list_edges(
    request: Request,
    node_id: str | None = None,
    caller: Caller = Depends(_personal),
) -> dict[str, Any]:
    kb = _knowledge(request)
    edges = kb.list_edges(node_id=node_id)
    return {
        "edges": [
            {
                "id": e.id,
                "source_id": e.source_id,
                "target_id": e.target_id,
                "type": e.type,
                "label": e.label,
                "roles": e.roles,
                "created_at": e.created_at,
            }
            for e in edges
        ]
    }


class EdgeCreateBody(BaseModel):
    source_id: str
    target_id: str
    type: str
    label: str = ""
    roles: list[str] = ["public"]


@router.post("/edges")
async def create_edge(
    body: EdgeCreateBody,
    request: Request,
    caller: Caller = Depends(_personal),
) -> dict[str, Any]:
    from .knowledge import EDGE_TYPES
    if body.type not in EDGE_TYPES:
        raise HTTPException(status_code=400, detail=f"Unknown edge type. Valid: {EDGE_TYPES}")
    kb = _knowledge(request)
    if not kb.get_node(body.source_id):
        raise HTTPException(status_code=404, detail="Source node not found")
    if not kb.get_node(body.target_id):
        raise HTTPException(status_code=404, detail="Target node not found")
    edge = kb.create_edge(
        source_id=body.source_id,
        target_id=body.target_id,
        type=body.type,
        label=body.label,
        roles=body.roles,
    )
    return {"ok": True, "id": edge.id}


@router.delete("/edges/{edge_id}")
async def delete_edge(
    edge_id: str,
    request: Request,
    caller: Caller = Depends(_personal),
) -> dict[str, Any]:
    kb = _knowledge(request)
    if not kb.delete_edge(edge_id):
        raise HTTPException(status_code=404, detail="Edge not found")
    return {"ok": True}


@router.get("/graph")
async def get_graph(
    request: Request,
    caller: Caller = Depends(_personal),
) -> dict[str, Any]:
    kb = _knowledge(request)
    # Admin sees the full graph regardless of roles
    return kb.get_graph(caller_roles=None)


# ── notebook endpoints ────────────────────────────────────────────────────────


@router.get("/notebooks")
async def list_notebooks(
    request: Request,
    caller: Caller = Depends(_personal),
) -> list[dict[str, Any]]:
    """Return notebook-root nodes with computed page counts."""
    from .knowledge import CONTAINMENT_EDGE_TYPES

    kb = _knowledge(request)
    nodes = kb.list_nodes()
    edges = kb.list_edges()

    # Find notebook roots: nodes with metadata.notebook_root == true
    notebook_ids = [n.id for n in nodes if n.metadata.get("notebook_root")]
    node_map = {n.id: n for n in nodes}

    # Build adjacency for containment edges (parent -> children)
    children_of: dict[str, list[str]] = {}
    for e in edges:
        if e.type in CONTAINMENT_EDGE_TYPES:
            # Normalise direction: parent -> child
            if e.type in ("member_of", "studied_at"):
                parent, child = e.target_id, e.source_id
            else:
                parent, child = e.source_id, e.target_id
            children_of.setdefault(parent, []).append(child)

    # Count all descendants for each notebook root
    def _count_descendants(root_id: str) -> int:
        count = 0
        stack = list(children_of.get(root_id, []))
        visited: set[str] = {root_id}
        while stack:
            nid = stack.pop()
            if nid in visited:
                continue
            visited.add(nid)
            count += 1
            stack.extend(children_of.get(nid, []))
        return count

    result = []
    for nb_id in notebook_ids:
        node = node_map.get(nb_id)
        if not node:
            continue
        result.append({
            "id": node.id,
            "title": node.title,
            "icon": node.metadata.get("icon", "📓"),
            "roles": node.roles,
            "page_count": _count_descendants(nb_id),
            "updated_at": node.updated_at,
            "order": node.metadata.get("order", 999),
        })
    result.sort(key=lambda x: x["order"])
    return result


@router.get("/notebooks/{notebook_id}/tree")
async def get_notebook_tree(
    notebook_id: str,
    request: Request,
    caller: Caller = Depends(_personal),
) -> dict[str, Any]:
    """Return the full containment tree rooted at this notebook as nested JSON."""
    from .knowledge import CONTAINMENT_EDGE_TYPES

    kb = _knowledge(request)
    node = kb.get_node(notebook_id)
    if not node:
        raise HTTPException(status_code=404, detail="Notebook not found")

    nodes = kb.list_nodes()
    edges = kb.list_edges()
    node_map = {n.id: n for n in nodes}

    # Build adjacency for containment edges (parent -> children)
    children_of: dict[str, list[str]] = {}
    for e in edges:
        if e.type in CONTAINMENT_EDGE_TYPES:
            if e.type in ("member_of", "studied_at"):
                parent, child = e.target_id, e.source_id
            else:
                parent, child = e.source_id, e.target_id
            children_of.setdefault(parent, []).append(child)

    # Primary parent resolution: for dedup in tree
    # Each node appears under its primary parent only
    primary_parent: dict[str, str] = {}
    for e in edges:
        if e.type not in CONTAINMENT_EDGE_TYPES:
            continue
        if e.type in ("member_of", "studied_at"):
            parent, child = e.target_id, e.source_id
        else:
            parent, child = e.source_id, e.target_id
        if child not in primary_parent:
            # Check metadata override
            child_node = node_map.get(child)
            if child_node and child_node.metadata.get("primary_parent"):
                primary_parent[child] = child_node.metadata["primary_parent"]
            else:
                primary_parent[child] = parent
        # Prefer 'has' edge type over others for default primary
        if e.type == "has" and not (node_map.get(child) or node).metadata.get("primary_parent"):
            primary_parent[child] = parent

    def _build_subtree(nid: str, visited: set[str]) -> dict[str, Any]:
        visited.add(nid)
        n = node_map.get(nid)
        child_ids = children_of.get(nid, [])
        # Filter: only children whose primary parent is this node
        own_children = [
            cid for cid in child_ids
            if cid not in visited and primary_parent.get(cid) == nid
        ]
        # Sort by metadata.order, then alphabetically
        own_children.sort(key=lambda cid: (
            node_map[cid].metadata.get("order", 999) if cid in node_map else 999,
            node_map[cid].title if cid in node_map else cid,
        ))
        return {
            "id": nid,
            "title": n.title if n else nid,
            "type": n.type if n else "unknown",
            "icon": (n.metadata.get("icon", "") if n else ""),
            "roles": n.roles if n else [],
            "has_body": bool(n and n.body and n.body.strip()),
            "updated_at": n.updated_at if n else "",
            "children": [_build_subtree(cid, visited) for cid in own_children],
        }

    tree = _build_subtree(notebook_id, set())
    return tree


# ── document upload / download ────────────────────────────────────────────────

_ALLOWED_SUFFIXES = {".pdf", ".docx", ".doc", ".txt", ".md"}


@router.post("/documents/upload")
async def upload_document(
    request: Request,
    file: UploadFile = File(...),
    title: str = Form(""),
    roles: str = Form("public,recruiter"),
    description: str = Form(""),
    caller: Caller = Depends(_personal),
) -> dict[str, Any]:
    """Upload a file (PDF, DOCX, TXT/MD), extract its text and store it as a
    *document* node in the knowledge graph so it is RAG-indexed automatically."""
    from .documents import extract_text, SUPPORTED_SUFFIXES

    original_name = file.filename or "document"
    suffix = Path(original_name).suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{suffix}'. Allowed: {sorted(SUPPORTED_SUFFIXES)}",
        )

    settings = get_settings()
    docs_dir = settings.documents_path
    docs_dir.mkdir(parents=True, exist_ok=True)

    # Store with a unique prefix to avoid collisions
    file_id = uuid.uuid4().hex[:8]
    stored_name = f"{file_id}{suffix}"
    dest = docs_dir / stored_name

    content = await file.read()
    dest.write_bytes(content)

    # Extract text for the node body
    body = extract_text(dest, file.content_type or "")
    if not body:
        body = f"[Document: {original_name} — text could not be extracted]"

    doc_title = title.strip() or Path(original_name).stem
    role_list = [r.strip() for r in roles.split(",") if r.strip()] or ["public"]

    kb = _knowledge(request)
    node = kb.create_node(
        type="document",
        title=doc_title,
        body=body,
        roles=role_list,
        metadata={
            "file_path": f"documents/{stored_name}",
            "original_filename": original_name,
            "mime_type": file.content_type or "",
            "size_bytes": len(content),
            "description": description,
        },
    )

    retriever = getattr(request.app.state, "retriever", None)
    if retriever is not None:
        retriever.reindex_node(node)

    log.info("uploaded document '%s' → node %s (%d bytes)", original_name, node.id, len(content))
    return {"ok": True, "id": node.id, "title": node.title, "size_bytes": len(content)}


@router.get("/documents/{node_id}/file")
async def download_document(
    node_id: str,
    request: Request,
    caller: Caller = Depends(_personal),
) -> FileResponse:
    """Return the primary attached file for a document node."""
    kb = _knowledge(request)
    node = kb.get_node(node_id)
    if not node or not node.metadata.get("file_path"):
        raise HTTPException(status_code=404, detail="No file attached to this node")

    file_rel = Path(node.metadata["file_path"])
    if file_rel.is_absolute() or ".." in file_rel.parts:
        raise HTTPException(status_code=400, detail="Invalid file path")

    settings = get_settings()
    full_path = settings.documents_path.parent / file_rel
    if not full_path.exists():
        raise HTTPException(status_code=404, detail="File not found on disk")

    return FileResponse(
        str(full_path),
        filename=node.metadata.get("original_filename") or full_path.name,
        media_type=node.metadata.get("mime_type") or "application/octet-stream",
    )


@router.get("/documents/{node_id}/files")
async def list_document_files(
    node_id: str,
    request: Request,
    caller: Caller = Depends(_personal),
) -> dict[str, Any]:
    """List all files attached to a node (primary + extra_files)."""
    kb = _knowledge(request)
    node = kb.get_node(node_id)
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")

    files: list[dict[str, Any]] = []
    if node.metadata.get("file_path"):
        files.append({
            "index": 0,
            "file_path": node.metadata["file_path"],
            "original_filename": node.metadata.get("original_filename") or "file",
            "mime_type": node.metadata.get("mime_type") or "application/octet-stream",
            "size_bytes": node.metadata.get("size_bytes"),
        })
    for i, ef in enumerate(node.metadata.get("extra_files", []), start=1):
        files.append({
            "index": i,
            "file_path": ef.get("file_path", ""),
            "original_filename": ef.get("original_filename") or "file",
            "mime_type": ef.get("mime_type") or "application/octet-stream",
            "size_bytes": ef.get("size_bytes"),
        })
    return {"files": files}


@router.get("/documents/{node_id}/file/{file_index}")
async def download_document_by_index(
    node_id: str,
    file_index: int,
    request: Request,
    caller: Caller = Depends(_personal),
) -> FileResponse:
    """Download a specific attached file by index (0 = primary, 1+ = extra_files)."""
    kb = _knowledge(request)
    node = kb.get_node(node_id)
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")

    settings = get_settings()

    if file_index == 0:
        if not node.metadata.get("file_path"):
            raise HTTPException(status_code=404, detail="No primary file attached")
        file_rel = Path(node.metadata["file_path"])
        filename = node.metadata.get("original_filename") or file_rel.name
        mime = node.metadata.get("mime_type") or "application/octet-stream"
    else:
        extra = node.metadata.get("extra_files", [])
        idx = file_index - 1
        if idx >= len(extra):
            raise HTTPException(status_code=404, detail="File index out of range")
        ef = extra[idx]
        file_rel = Path(ef.get("file_path", ""))
        filename = ef.get("original_filename") or file_rel.name
        mime = ef.get("mime_type") or "application/octet-stream"

    if file_rel.is_absolute() or ".." in file_rel.parts:
        raise HTTPException(status_code=400, detail="Invalid file path")

    full_path = settings.documents_path.parent / file_rel
    if not full_path.exists():
        raise HTTPException(status_code=404, detail="File not found on disk")

    return FileResponse(str(full_path), filename=filename, media_type=mime)


@router.post("/nodes/{node_id}/attach")
async def attach_file_to_node(
    node_id: str,
    request: Request,
    file: UploadFile = File(...),
    caller: Caller = Depends(_personal),
) -> dict[str, Any]:
    """Attach (or replace) a file on any existing node."""
    from .documents import extract_text, SUPPORTED_SUFFIXES

    kb = _knowledge(request)
    node = kb.get_node(node_id)
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")

    original_name = file.filename or "document"
    suffix = Path(original_name).suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{suffix}'. Allowed: {sorted(SUPPORTED_SUFFIXES)}",
        )

    settings = get_settings()
    docs_dir = settings.documents_path
    docs_dir.mkdir(parents=True, exist_ok=True)

    # Remove the old file if one was already attached
    old_path = node.metadata.get("file_path", "")
    if old_path:
        old_file = settings.documents_path.parent / Path(old_path)
        try:
            old_file.unlink(missing_ok=True)
        except Exception as exc:  # noqa: BLE001
            log.warning("could not delete old attachment %s: %s", old_file, exc)

    file_id = uuid.uuid4().hex[:8]
    stored_name = f"{file_id}{suffix}"
    dest = docs_dir / stored_name

    content = await file.read()
    dest.write_bytes(content)

    new_metadata = {
        **node.metadata,
        "file_path": f"documents/{stored_name}",
        "original_filename": original_name,
        "mime_type": file.content_type or "",
        "size_bytes": len(content),
    }

    updated = kb.update_node(node_id, metadata=new_metadata)
    retriever = getattr(request.app.state, "retriever", None)
    if retriever is not None and updated:
        retriever.reindex_node(updated)

    log.info("attached '%s' to node %s (%d bytes)", original_name, node_id, len(content))
    return {"ok": True, "file_path": f"documents/{stored_name}", "size_bytes": len(content)}


@router.delete("/nodes/{node_id}/attachment")
async def detach_file_from_node(
    node_id: str,
    request: Request,
    caller: Caller = Depends(_personal),
) -> dict[str, Any]:
    """Remove the file attached to a node (deletes the file on disk)."""
    kb = _knowledge(request)
    node = kb.get_node(node_id)
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")

    file_path = node.metadata.get("file_path", "")
    if not file_path:
        raise HTTPException(status_code=404, detail="No file attached to this node")

    settings = get_settings()
    file_rel = Path(file_path)
    if not file_rel.is_absolute() and ".." not in file_rel.parts:
        try:
            (settings.documents_path.parent / file_rel).unlink(missing_ok=True)
        except Exception as exc:  # noqa: BLE001
            log.warning("could not delete attachment %s: %s", file_rel, exc)

    new_metadata = {k: v for k, v in node.metadata.items()
                    if k not in ("file_path", "original_filename", "mime_type", "size_bytes")}
    updated = kb.update_node(node_id, metadata=new_metadata)
    retriever = getattr(request.app.state, "retriever", None)
    if retriever is not None and updated:
        retriever.reindex_node(updated)

    return {"ok": True}


# ── M28 — Memory management chat ──────────────────────────────────────────────

_MEMORY_CHAT_SYSTEM = """You are a knowledge graph assistant with full read/write access to \
Sebastiaan's digital twin memory graph.

Available tools (call them by JSON function-call blocks when needed):
- list_nodes(type_filter?)           — list all nodes, optionally filtered by type
- get_node(id)                       — fetch a node's full content including body markdown
- search_nodes(query)                — full-text search across titles and bodies
- update_node(id, title?, body?, roles?)  — update fields on an existing node
- create_node(type, title, body, roles)   — create a new node
- list_edges(node_id?)               — list edges, optionally for one node
- create_edge(source_id, target_id, type, label?)  — add a relationship
- delete_edge(id)                    — remove a relationship

Node types: person, job, project, skill, education, community, document, opinion, personal, faq, system
Edge types: worked_at, built, knows, studied_at, member_of, relates_to, used_in, describes, authored, has, includes, uses

When updating node bodies use clean Markdown. Keep changes minimal and accurate.
Always confirm what you did after executing a tool.
"""

_MEMORY_TOOLS_OPENAI = [
    {
        "type": "function",
        "function": {
            "name": "list_nodes",
            "description": "List knowledge graph nodes with optional type filter.",
            "parameters": {
                "type": "object",
                "properties": {
                    "type_filter": {"type": "string", "description": "e.g. job, project, person"}
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_node",
            "description": "Fetch a single node including its full body markdown.",
            "parameters": {
                "type": "object",
                "required": ["id"],
                "properties": {"id": {"type": "string"}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_nodes",
            "description": "Full-text search across node titles and bodies.",
            "parameters": {
                "type": "object",
                "required": ["query"],
                "properties": {"query": {"type": "string"}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_node",
            "description": "Update fields on an existing node.",
            "parameters": {
                "type": "object",
                "required": ["id"],
                "properties": {
                    "id": {"type": "string"},
                    "title": {"type": "string"},
                    "body": {"type": "string", "description": "New markdown body"},
                    "roles": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "e.g. [\"public\",\"recruiter\"]",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_node",
            "description": "Create a new knowledge graph node.",
            "parameters": {
                "type": "object",
                "required": ["type", "title"],
                "properties": {
                    "type": {"type": "string"},
                    "title": {"type": "string"},
                    "body": {"type": "string"},
                    "roles": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_edges",
            "description": "List graph edges, optionally filtered to a single node.",
            "parameters": {
                "type": "object",
                "properties": {"node_id": {"type": "string"}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_edge",
            "description": "Create a relationship between two nodes.",
            "parameters": {
                "type": "object",
                "required": ["source_id", "target_id", "type"],
                "properties": {
                    "source_id": {"type": "string"},
                    "target_id": {"type": "string"},
                    "type": {"type": "string"},
                    "label": {"type": "string"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_edge",
            "description": "Remove a relationship edge by ID.",
            "parameters": {
                "type": "object",
                "required": ["id"],
                "properties": {"id": {"type": "string"}},
            },
        },
    },
]

# Anthropic tool format (converted from OpenAI format above)
_MEMORY_TOOLS_ANTHROPIC = [
    {
        "name": t["function"]["name"],
        "description": t["function"]["description"],
        "input_schema": t["function"]["parameters"],
    }
    for t in _MEMORY_TOOLS_OPENAI
]


async def _execute_memory_tool(name: str, args: dict[str, Any], kb) -> Any:
    """Execute a single memory tool call and return the result dict."""
    from .knowledge import NODE_TYPES, EDGE_TYPES

    if name == "list_nodes":
        nodes = kb.list_nodes(type_filter=args.get("type_filter"))
        return {
            "nodes": [
                {"id": n.id, "type": n.type, "title": n.title, "roles": n.roles}
                for n in nodes
            ]
        }

    if name == "get_node":
        node = kb.get_node(args["id"])
        if not node:
            return {"error": f"Node '{args['id']}' not found"}
        return {
            "id": node.id, "type": node.type, "title": node.title,
            "body": node.body, "roles": node.roles,
        }

    if name == "search_nodes":
        nodes = kb.search_nodes(args.get("query", ""))
        return {
            "nodes": [
                {"id": n.id, "type": n.type, "title": n.title,
                 "preview": n.body[:120] if n.body else ""}
                for n in nodes
            ]
        }

    if name == "update_node":
        node_id = args.get("id", "")
        updates: dict[str, Any] = {}
        if "title" in args:
            updates["title"] = args["title"]
        if "body" in args:
            updates["body"] = args["body"]
        if "roles" in args:
            updates["roles"] = args["roles"]
        node = kb.update_node(node_id, **updates)
        if not node:
            return {"error": f"Node '{node_id}' not found"}
        return {"ok": True, "id": node.id, "title": node.title, "updated_at": node.updated_at}

    if name == "create_node":
        node_type = args.get("type", "document")
        if node_type not in NODE_TYPES:
            return {"error": f"Invalid type '{node_type}'. Valid: {NODE_TYPES}"}
        node = kb.create_node(
            type=node_type,
            title=args.get("title", "Untitled"),
            body=args.get("body", ""),
            roles=args.get("roles", ["public"]),
        )
        return {"ok": True, "id": node.id, "type": node.type, "title": node.title}

    if name == "list_edges":
        edges = kb.list_edges(node_id=args.get("node_id"))
        return {
            "edges": [
                {
                    "id": e.id, "source": e.source_id, "target": e.target_id,
                    "type": e.type, "label": e.label,
                }
                for e in edges
            ]
        }

    if name == "create_edge":
        src_id, tgt_id = args.get("source_id", ""), args.get("target_id", "")
        edge_type = args.get("type", "relates_to")
        if edge_type not in EDGE_TYPES:
            return {"error": f"Invalid edge type '{edge_type}'. Valid: {EDGE_TYPES}"}
        if not kb.get_node(src_id):
            return {"error": f"Source node '{src_id}' not found"}
        if not kb.get_node(tgt_id):
            return {"error": f"Target node '{tgt_id}' not found"}
        edge = kb.create_edge(
            source_id=src_id, target_id=tgt_id,
            type=edge_type, label=args.get("label", ""),
        )
        return {"ok": True, "id": edge.id, "source": edge.source_id, "target": edge.target_id}

    if name == "delete_edge":
        ok = kb.delete_edge(args.get("id", ""))
        return {"ok": ok}

    return {"error": f"Unknown tool '{name}'"}


async def _stream_memory_chat_openai(
    provider,
    messages: list[dict[str, Any]],
    kb,
) -> AsyncIterator[dict[str, Any]]:
    """Tool-calling loop for OpenAI providers."""
    max_rounds = 6
    for _ in range(max_rounds):
        response = await provider._client.chat.completions.create(
            model=provider.model,
            messages=messages,
            tools=_MEMORY_TOOLS_OPENAI,
            tool_choice="auto",
            max_tokens=2000,
        )
        msg = response.choices[0].message

        if msg.tool_calls:
            # Emit tool-call events and execute them
            calls_payload = [
                {"id": tc.id, "name": tc.function.name, "args": tc.function.arguments}
                for tc in msg.tool_calls
            ]
            yield {"type": "tool_calls", "calls": calls_payload}

            # Append assistant message (with tool_calls) to history
            messages.append(msg.model_dump(exclude_unset=True))

            # Execute each tool and append tool results
            for tc in msg.tool_calls:
                try:
                    args = json.loads(tc.function.arguments)
                except json.JSONDecodeError:
                    args = {}
                result = await _execute_memory_tool(tc.function.name, args, kb)
                yield {"type": "tool_result", "name": tc.function.name, "result": result}
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": json.dumps(result),
                })
        else:
            # Final answer — stream character by character is overkill here;
            # yield the full text as a single chunk then done.
            text = msg.content or ""
            yield {"type": "chunk", "text": text}
            yield {"type": "done"}
            return

    yield {"type": "error", "text": "Max tool-call rounds reached."}
    yield {"type": "done"}


async def _stream_memory_chat_anthropic(
    provider,
    messages: list[dict[str, Any]],
    kb,
) -> AsyncIterator[dict[str, Any]]:
    """Tool-calling loop for Anthropic providers."""
    import anthropic as anthropic_sdk

    max_rounds = 6
    system_msg = messages[0]["content"] if messages and messages[0]["role"] == "system" else ""
    conv = [m for m in messages if m.get("role") != "system"]

    for _ in range(max_rounds):
        response = await provider._client.messages.create(
            model=provider.model,
            system=system_msg,
            messages=conv,
            tools=_MEMORY_TOOLS_ANTHROPIC,
            max_tokens=2000,
        )

        # Collect text and tool_use blocks
        text_parts: list[str] = []
        tool_uses: list[Any] = []
        for block in response.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_uses.append(block)

        if response.stop_reason == "tool_use" and tool_uses:
            calls_payload = [
                {"id": tu.id, "name": tu.name, "args": json.dumps(tu.input)}
                for tu in tool_uses
            ]
            yield {"type": "tool_calls", "calls": calls_payload}

            # Append assistant turn
            conv.append({"role": "assistant", "content": response.content})

            # Execute tools and append user turn with results
            tool_results = []
            for tu in tool_uses:
                result = await _execute_memory_tool(tu.name, tu.input, kb)
                yield {"type": "tool_result", "name": tu.name, "result": result}
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tu.id,
                    "content": json.dumps(result),
                })
            conv.append({"role": "user", "content": tool_results})
        else:
            text = " ".join(text_parts).strip()
            yield {"type": "chunk", "text": text}
            yield {"type": "done"}
            return

    yield {"type": "error", "text": "Max tool-call rounds reached."}
    yield {"type": "done"}


async def _stream_memory_chat_fallback(
    provider,
    messages: list[dict[str, Any]],
    kb,
) -> AsyncIterator[dict[str, Any]]:
    """Simple streaming fallback for providers without tool-calling (e.g. Ollama)."""
    from .providers.base import Message as ProviderMessage

    system_msg = messages[0]["content"] if messages and messages[0]["role"] == "system" else ""
    history = [
        ProviderMessage(role=m["role"], content=m["content"])
        for m in messages
        if m.get("role") in {"user", "assistant"} and isinstance(m.get("content"), str)
    ]
    text = ""
    async for token, _ in provider.stream(system=system_msg, messages=history, max_tokens=1500):
        if token:
            text += token
    yield {"type": "chunk", "text": text}
    yield {"type": "done"}


class MemoryChatBody(BaseModel):
    message: str
    history: list[dict[str, Any]] = []


@router.post("/memory-chat")
async def memory_chat(
    body: MemoryChatBody,
    request: Request,
    caller: Caller = Depends(_personal),
):
    """SSE streaming memory management chat with tool use (M28).

    Streams events:
      {"type": "tool_calls", "calls": [...]}
      {"type": "tool_result", "name": "...", "result": {...}}
      {"type": "chunk", "text": "..."}
      {"type": "done"}
      {"type": "error", "text": "..."}
    """
    kb = _knowledge(request)
    provider = request.app.state.provider

    # Build message list with system prompt first
    messages: list[dict[str, Any]] = [{"role": "system", "content": _MEMORY_CHAT_SYSTEM}]
    for turn in body.history:
        role = turn.get("role", "user")
        content = turn.get("content", "")
        if role in {"user", "assistant"} and content:
            messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": body.message})

    async def generate():
        try:
            if provider.name == "openai":
                aiter = _stream_memory_chat_openai(provider, messages, kb)
            elif provider.name == "anthropic":
                aiter = _stream_memory_chat_anthropic(provider, messages, kb)
            else:
                aiter = _stream_memory_chat_fallback(provider, messages, kb)

            async for event in aiter:
                yield {"data": json.dumps(event)}
        except Exception as exc:
            log.exception("memory-chat error")
            yield {"data": json.dumps({"type": "error", "text": str(exc)})}

    return EventSourceResponse(generate())


# ── Eval runs ─────────────────────────────────────────────────────────────────
# Read / annotate golden-test result files from logs/golden_results_*.json


def _eval_runs_dir() -> Path:
    return Path(get_settings().log_file).parent


def _load_run(path: Path) -> dict:
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def _run_summary(path: Path) -> dict:
    """Return lightweight metadata for listing runs."""
    try:
        d = _load_run(path)
        cases = d.get("cases", [])
        passed = sum(1 for c in cases if c.get("passed"))
        return {
            "name": path.name,
            "run_at": d.get("run_at"),
            "label": d.get("label"),
            "model": d.get("model"),
            "provider": d.get("provider"),
            "total": len(cases),
            "passed": passed,
            "failed": len(cases) - passed,
            "notes": d.get("notes", ""),
        }
    except Exception as exc:
        return {"name": path.name, "error": str(exc)}


@router.get("/eval/runs")
async def list_eval_runs(caller: Caller = Depends(_personal)) -> dict:
    """List all golden-test result files, newest first.

    ``golden_results_latest.json`` is always a copy of the most recent labeled
    run — it is excluded from the listing to avoid duplicates.
    """
    logs_dir = _eval_runs_dir()
    files = sorted(
        [
            p for p in logs_dir.glob("golden_results_*.json")
            if p.name != "golden_results_latest.json"
        ],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return {"runs": [_run_summary(p) for p in files]}


@router.get("/eval/runs/{name}")
async def get_eval_run(name: str, caller: Caller = Depends(_personal)) -> dict:
    """Return full contents of a single run file."""
    # Safety: only allow simple filenames, no path traversal
    if "/" in name or "\\" in name or not name.endswith(".json"):
        raise HTTPException(status_code=400, detail="Invalid run name")
    path = _eval_runs_dir() / name
    if not path.exists():
        raise HTTPException(status_code=404, detail="Run not found")
    return _load_run(path)


class EvalNotesBody(BaseModel):
    notes: str | None = None  # run-level note
    case_notes: dict[str, str] | None = None  # {case_id: note}


@router.patch("/eval/runs/{name}")
async def patch_eval_run(
    name: str,
    body: EvalNotesBody,
    caller: Caller = Depends(_personal),
) -> dict:
    """Save run-level notes and/or per-case notes to a result file."""
    if "/" in name or "\\" in name or not name.endswith(".json"):
        raise HTTPException(status_code=400, detail="Invalid run name")
    path = _eval_runs_dir() / name
    if not path.exists():
        raise HTTPException(status_code=404, detail="Run not found")

    data = _load_run(path)

    if body.notes is not None:
        data["notes"] = body.notes

    if body.case_notes:
        for case in data.get("cases", []):
            cid = case.get("id")
            if cid and cid in body.case_notes:
                case["notes"] = body.case_notes[cid]

    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return {"ok": True}
