"""Microsoft Teams Outgoing Webhook handler.

Teams POSTs a JSON payload whenever a user @mentions the webhook in a channel.
We strip the @mention, run the query through the existing RAG + LLM pipeline
using the **work** role (public + work content only), and return a plain-text
or Adaptive-Card response within the 10-second Teams timeout.

Security: each request carries an Authorization header with an HMAC-SHA256
signature derived from the shared secret Teams provides when the webhook is
created.  We verify that signature before processing.

Environment variable:
    TEAMS_WEBHOOK_SECRET  –  the base64-encoded HMAC token Teams shows during
                             webhook creation.  Leave empty to disable
                             signature verification (development only).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import re
import time

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from .config import get_settings
from .providers import LLMProvider, Message
from .rag import RAGRetriever

log = logging.getLogger("ask-my-agent.teams")

router = APIRouter()

# Roles assigned to every Teams webhook caller — public + work content only.
_TEAMS_ROLES: list[str] = ["public", "work"]

# Regex to strip the HTML <at>…</at> mention that Teams injects.
_AT_MENTION_RE = re.compile(r"<at>.*?</at>\s*", re.IGNORECASE)


def _verify_hmac(body: bytes, auth_header: str, secret_b64: str) -> bool:
    """Validate the HMAC-SHA256 signature Teams sends in the Authorization header.

    Teams sends: ``HMAC <base64-signature>``
    We compute HMAC-SHA256(secret, body) and compare.
    """
    if not auth_header.upper().startswith("HMAC "):
        return False
    sig_b64 = auth_header[5:].strip()
    try:
        expected = base64.b64decode(sig_b64)
        secret = base64.b64decode(secret_b64)
    except Exception:
        return False
    computed = hmac.new(secret, body, hashlib.sha256).digest()
    return hmac.compare_digest(computed, expected)


@router.post("/api/teams/webhook")
async def teams_webhook(request: Request):
    """Handle an Outgoing Webhook call from Microsoft Teams."""
    started = time.time()

    # ── 1. Read & verify ────────────────────────────────────────────────
    raw_body = await request.body()
    settings = get_settings()
    secret = settings.teams_webhook_secret

    if secret:
        auth = request.headers.get("Authorization", "")
        if not _verify_hmac(raw_body, auth, secret):
            log.warning("teams webhook: HMAC verification failed")
            raise HTTPException(status_code=401, detail="Invalid HMAC signature")
    else:
        log.debug("teams webhook: HMAC verification skipped (no secret configured)")

    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    # ── 2. Extract the user question ────────────────────────────────────
    raw_text: str = payload.get("text", "")
    # Strip the @mention tag Teams wraps around the webhook name.
    user_question = _AT_MENTION_RE.sub("", raw_text).strip()
    if not user_question:
        return _text_response("I didn't catch a question — try @mentioning me followed by your question.")

    from_name: str = (payload.get("from") or {}).get("name", "Someone")
    log.info("teams webhook query from %s: %s", from_name, user_question[:120])

    # ── 3. Retrieve context (work-tier only) ────────────────────────────
    retriever: RAGRetriever = request.app.state.retriever
    provider: LLMProvider = request.app.state.provider

    chunks = retriever.retrieve(user_turns=[user_question], caller_roles=_TEAMS_ROLES)
    system_text = request.app.state.knowledge.get_system_prompt() or ""
    context = retriever.context_block(chunks)
    full_system = system_text + ("\n\n" + context if context else "")

    # Add a Teams-specific system instruction so the LLM keeps answers concise.
    full_system += (
        "\n\nYou are responding inside a Microsoft Teams channel. "
        "Keep your answer concise (a few paragraphs max). "
        "You are speaking to a work colleague of Sebastiaan. "
        "Only share information appropriate for a professional/work context."
    )

    messages = [Message(role="user", content=user_question)]

    # ── 4. Generate (non-streaming, collect full response) ──────────────
    full_text: list[str] = []
    try:
        async for token, _meta in provider.stream(
            system=full_system,
            messages=messages,
            max_tokens=600,
        ):
            if token:
                full_text.append(token)
            # Bail early if we're approaching the Teams 10s limit.
            if time.time() - started > 8.5:
                full_text.append("\n\n_(response trimmed — Teams has a 10-second limit)_")
                break
    except Exception:
        log.exception("teams webhook: LLM stream failed")
        return _text_response("Sorry, I hit an error generating a response. Please try again.")

    answer = "".join(full_text).strip() or "I couldn't generate a response for that."
    elapsed = time.time() - started
    log.info("teams webhook responded in %.1fs (%d chars)", elapsed, len(answer))

    return _text_response(answer)


def _text_response(text: str) -> JSONResponse:
    """Return a Teams-compatible bot response with a plain text message."""
    return JSONResponse(content={"type": "message", "text": text})
