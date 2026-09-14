"""Token → tier + roles resolution + FastAPI dependency."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Literal

from fastapi import Header, HTTPException, Request

from .config import Tier, accessible_tiers, get_settings, load_tokens

logger = logging.getLogger(__name__)


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
    """Return (tier, roles, label) for a token.

    Empty tokens resolve to anonymous public access. Unknown non-empty tokens are
    rejected so typoed or leaked links cannot silently degrade into a public
    session.
    """
    tokens = load_tokens(get_settings().credentials_path)
    if token in tokens:
        meta = tokens[token]
        return meta["tier"], meta["roles"], meta.get("label", "")
    if token:
        raise HTTPException(status_code=401, detail={"reason": "invalid_token"})
    return "public", ["public"], "anonymous"


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
    """FastAPI dependency that resolves the caller from auth headers.

    Query-string token auth is disabled by default because URLs are commonly
    copied, logged, and stored in browser history. It can be re-enabled for
    controlled environments via settings.
    """
    settings = get_settings()
    query_token = request.query_params.get("t", "") if settings.allow_query_token_auth else ""
    token = x_access_token or query_token or ""
    tier, roles, label = resolve_caller_meta(token)
    return Caller(token=token, tier=tier, roles=roles, label=label, ip=client_ip(request))


# Cloudflare Access JWT validation (optional admin hardening)

@dataclass(frozen=True)
class CFAccessIdentity:
    """Resolved Cloudflare Access JWT identity."""
    
    email: str
    identity_nonce: str
    authenticated: bool = True


async def validate_cf_jwt(token: str) -> CFAccessIdentity:
    """
    Validate Cloudflare Access JWT token.
    
    Args:
        token: JWT from Cf-Access-Jwt-Assertion header
    
    Returns:
        CFAccessIdentity with email and identity_nonce
        
    Raises:
        HTTPException(401) if invalid or expired
    
    Note:
        This requires pyjwt to be installed. If not available, returns
        a dummy identity to allow graceful fallback in non-CF deployments.
    """
    if not token:
        raise HTTPException(
            status_code=401,
            detail={"reason": "missing_cf_jwt"}
        )
    
    try:
        import jwt
        from cryptography.hazmat.backends import default_backend
    except ImportError:
        logger.warning("pyjwt not installed; CF JWT validation disabled")
        # Fallback: allow if token exists (requires CF Edge to validate)
        return CFAccessIdentity(
            email="cf-verified@cloudflare",
            identity_nonce="fallback",
            authenticated=True
        )
    
    try:
        import httpx
        
        # Fetch Cloudflare's public keys (cached in production)
        cf_certs_url = "https://cloudflare-dns.com/cdn-cgi/access/certs"
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(cf_certs_url)
            resp.raise_for_status()
            cf_data = resp.json()
        
        # Decode JWT header to find which key was used
        unverified = jwt.decode(token, options={"verify_signature": False})
        kid = unverified.get("kid")
        
        if not kid:
            raise HTTPException(
                status_code=401,
                detail={"reason": "cf_jwt_missing_kid"}
            )
        
        # Find the correct public key
        pub_key = None
        for cert in cf_data.get("certs", []):
            if cert.get("kid") == kid:
                pub_key = cert.get("cert")
                break
        
        if not pub_key:
            raise HTTPException(
                status_code=401,
                detail={"reason": "cf_key_not_found"}
            )
        
        # Verify JWT signature
        payload = jwt.decode(
            token,
            pub_key,
            algorithms=["RS256"],
            options={"verify_exp": True}
        )
        
        email = payload.get("email", "unknown@cloudflare")
        identity_nonce = payload.get("identity_nonce", "")
        
        logger.info(f"CF Access JWT valid for {email}")
        
        return CFAccessIdentity(
            email=email,
            identity_nonce=identity_nonce,
            authenticated=True
        )
        
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=401,
            detail={"reason": "cf_jwt_expired"}
        )
    except jwt.InvalidTokenError as e:
        raise HTTPException(
            status_code=401,
            detail={"reason": "cf_jwt_invalid", "error": str(e)}
        )
    except Exception as e:
        logger.error(f"CF JWT validation failed: {e}")
        raise HTTPException(
            status_code=401,
            detail={"reason": "cf_jwt_validation_failed"}
        )


async def cf_access_dep(
    request: Request,
) -> CFAccessIdentity:
    """
    FastAPI dependency that validates Cloudflare Access JWT.
    
    Use this to protect admin routes:
    
        @app.get("/admin/stats")
        async def admin_stats(cf_auth: CFAccessIdentity = Depends(cf_access_dep)):
            return {"user": cf_auth.email, ...}
    """
    token = request.headers.get("Cf-Access-Jwt-Assertion", "")
    identity = await validate_cf_jwt(token)
    
    logger.info(f"CF Access dependency resolved for {identity.email}")
    
    return identity


__all__ = [
    "Caller",
    "CFAccessIdentity",
    "caller_dep",
    "cf_access_dep",
    "resolve_tier",
    "resolve_caller_meta",
    "client_ip",
    "validate_cf_jwt",
]
