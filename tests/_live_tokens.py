from __future__ import annotations

import os
from pathlib import Path

import yaml


_ROOT = Path(__file__).resolve().parent.parent
_CREDENTIALS_FILE = _ROOT / "credentials.yaml"


def _bucket_for_meta(meta: dict) -> str | None:
    roles = [str(role) for role in (meta.get("roles") or [])]
    if "personal" in roles:
        return "personal"
    if "work" in roles or "recruiter" in roles:
        return "recruiter"

    tier = str(meta.get("tier") or "public")
    if tier == "personal":
        return "personal"
    if tier in {"work", "recruiter"}:
        return "recruiter"
    if tier == "public":
        return "public"
    return None


def load_live_tokens() -> dict[str, str | None]:
    tokens: dict[str, str | None] = {
        "public": os.environ.get("TOKEN_PUBLIC") or None,
        "recruiter": os.environ.get("TOKEN_RECRUITER") or None,
        "personal": os.environ.get("TOKEN_PERSONAL") or None,
    }

    if _CREDENTIALS_FILE.exists():
        data = yaml.safe_load(_CREDENTIALS_FILE.read_text(encoding="utf-8")) or {}
        for token, meta in (data.get("tokens") or {}).items():
            bucket = _bucket_for_meta(meta or {})
            if bucket and tokens.get(bucket) is None:
                tokens[bucket] = token or None

    return tokens


def require_token_for_tier(tokens: dict[str, str | None], tier: str) -> str | None:
    token = tokens.get(tier)
    if tier == "public" or token:
        return token

    env_name = {
        "recruiter": "TOKEN_RECRUITER",
        "personal": "TOKEN_PERSONAL",
    }.get(tier, "TOKEN_PUBLIC")
    raise RuntimeError(
        f"Missing {tier} access token. Set {env_name} or create {_CREDENTIALS_FILE}."
    )