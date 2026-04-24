"""Token → tier + roles resolution + FastAPI dependency."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from fastapi import Header, Request

from .config import Tier, accessible_tiers, get_settings, load_tokens


@dataclass(frozen=True)
class Caller:
    """Resolved identity for a single request."""

    token: str
    tier: Tier
    roles: list[str]
    label: str
    ip: str

    @property
    def tiers(self) -> list[Tier]:
        """Backward-compat: accessible tier hierarchy for rate limiting."""
        return accessible_tiers(self.tier)

    @property
    def key(self) -> str:
        """Rate-limit bucket key: `ip:token` (empty token kept as empty string)."""
        return f"{self.ip}:{self.token}"


def resolve_caller_meta(token: str) -> tuple[Tier, list[str], str]:
    """Return (tier, roles, label) for a token. Unknown tokens → public."""
    tokens = load_tokens(get_settings().credentials_path)
    if token in tokens:
        meta = tokens[token]
        return meta["tier"], meta["roles"], meta.get("label", "")
    return "public", ["public"], "unknown token (fallback public)"


def resolve_tier(token: str) -> tuple[Tier, str]:
    """Backward-compat shim used by tests."""
    tier, _, label = resolve_caller_meta(token)
    return tier, label


def client_ip(request: Request) -> str:
    """Best-effort client IP (honours X-Forwarded-For when behind Cloudflare Tunnel)."""
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    if request.client:
        return request.client.host
    return "0.0.0.0"


async def caller_dep(
    request: Request,
    x_access_token: str | None = Header(default=None, alias="X-Access-Token"),
) -> Caller:
    """FastAPI dependency that resolves the caller from X-Access-Token or ?t=query."""
    token = x_access_token or request.query_params.get("t", "") or ""
    tier, roles, label = resolve_caller_meta(token)
    return Caller(token=token, tier=tier, roles=roles, label=label, ip=client_ip(request))


__all__ = ["Caller", "caller_dep", "resolve_tier", "resolve_caller_meta", "client_ip"]
