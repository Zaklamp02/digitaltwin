"""Telegram owner notifications — fire-and-forget, never blocks chat."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import httpx

log = logging.getLogger("ask-my-agent.notify")

_AMS = ZoneInfo("Europe/Amsterdam")


async def notify_new_conversation(
    *,
    tier: str,
    ip_hash: str,
    first_message: str,
    bot_token: str,
    chat_id: str,
) -> None:
    """Send a Telegram message for a new conversation. No-op if creds are missing."""
    if not bot_token or not chat_id:
        return

    now = datetime.now(tz=_AMS).strftime("%H:%M %Z")
    preview = first_message[:80].replace("\n", " ")
    if len(first_message) > 80:
        preview += "…"

    tier_emoji = {"public": "🟢", "recruiter": "🟡", "personal": "🔵"}.get(tier, "⚪")
    # Recruiter-tier gets an extra call-out line to surface it quickly
    extra = "\n🔔 <b>Recruiter access</b> — check follow-up!" if tier == "recruiter" else ""
    text = f"{tier_emoji} New chat [{tier}] @ {now}\n\"{preview}\"{extra}"

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}

    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.post(url, json=payload)
            if r.status_code != 200:
                log.warning("telegram notify failed: %s %s", r.status_code, r.text[:120])
    except Exception as exc:  # noqa: BLE001
        log.warning("telegram notify error: %s", exc)


def fire(
    *,
    tier: str,
    ip_hash: str,
    first_message: str,
    bot_token: str,
    chat_id: str,
) -> None:
    """Schedule the notification as a background asyncio task."""
    asyncio.ensure_future(
        notify_new_conversation(
            tier=tier,
            ip_hash=ip_hash,
            first_message=first_message,
            bot_token=bot_token,
            chat_id=chat_id,
        )
    )
