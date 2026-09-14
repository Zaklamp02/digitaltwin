"""Auth + rate-limit tests."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
from fastapi import Depends, FastAPI, HTTPException
from fastapi.testclient import TestClient

import app.auth as auth_module

from app.auth import caller_dep, resolve_caller_meta
from app.config import Settings, accessible_tiers, load_tokens
from app.session import SessionStore, conv_limit, turn_limit


def _write_credentials(path: Path) -> None:
    path.write_text(textwrap.dedent("""\
        tokens:
          "":
            tier: public
            label: anonymous
          "rec-abc":
            tier: recruiter
            label: recruiter link
          "pers-xyz":
            tier: personal
            label: inner circle
    """), encoding="utf-8")


def test_load_tokens_and_tier_hierarchy(tmp_path: Path) -> None:
    creds = tmp_path / "credentials.yaml"
    _write_credentials(creds)
    tokens = load_tokens(creds)
    assert tokens[""]["tier"] == "public"
    assert tokens["rec-abc"]["tier"] == "work"
    assert tokens["pers-xyz"]["tier"] == "personal"

    assert accessible_tiers("public") == ["public"]
    assert accessible_tiers("work") == ["public", "work"]
    assert accessible_tiers("personal") == ["public", "work", "friends", "personal"]


def test_unknown_token_is_a_safe_default(tmp_path: Path) -> None:
    # Missing file → we still get a public entry so requests don't 500.
    missing = tmp_path / "nope.yaml"
    tokens = load_tokens(missing)
    assert tokens[""]["tier"] == "public"


def test_empty_token_resolves_to_anonymous_public(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    creds = tmp_path / "credentials.yaml"
    _write_credentials(creds)
    monkeypatch.setattr(auth_module, "get_settings", lambda: Settings(credentials_file=str(creds)))

    tier, roles, label = resolve_caller_meta("")
    assert tier == "public"
    assert roles == ["public"]
    assert label == "anonymous"


def test_unknown_non_empty_token_is_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    creds = tmp_path / "credentials.yaml"
    _write_credentials(creds)
    monkeypatch.setattr(auth_module, "get_settings", lambda: Settings(credentials_file=str(creds)))

    with pytest.raises(HTTPException) as exc:
        resolve_caller_meta("bogus-token")

    assert exc.value.status_code == 401


def _make_whoami_app() -> FastAPI:
    app = FastAPI()

    @app.get("/whoami")
    async def whoami_route(caller=Depends(caller_dep)):
        return {"tier": caller.tier, "token": caller.token}

    return app


def test_query_param_token_auth_disabled_by_default(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    creds = tmp_path / "credentials.yaml"
    _write_credentials(creds)
    monkeypatch.setattr(
        auth_module,
        "get_settings",
        lambda: Settings(credentials_file=str(creds), allow_query_token_auth=False),
    )

    client = TestClient(_make_whoami_app())
    response = client.get("/whoami?t=pers-xyz")

    assert response.status_code == 200
    assert response.json() == {"tier": "public", "token": ""}


def test_query_param_token_auth_can_be_enabled(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    creds = tmp_path / "credentials.yaml"
    _write_credentials(creds)
    monkeypatch.setattr(
        auth_module,
        "get_settings",
        lambda: Settings(credentials_file=str(creds), allow_query_token_auth=True),
    )

    client = TestClient(_make_whoami_app())
    response = client.get("/whoami?t=pers-xyz")

    assert response.status_code == 200
    assert response.json() == {"tier": "personal", "token": "pers-xyz"}


def test_conversation_and_turn_limits() -> None:
    # public: 3 conversations/day, 10 turns/conversation.
    assert conv_limit("public") == 3
    assert turn_limit("public") == 10
    assert conv_limit("work") == 10
    assert turn_limit("work") == 25
    # personal is unlimited (-1)
    assert conv_limit("personal") == -1
    assert turn_limit("personal") == -1


def test_session_store_respects_conversation_quota() -> None:
    store = SessionStore()
    ip, token = "1.2.3.4", ""
    # public → 3 conversations allowed
    for i in range(3):
        ok, used, limit = store.check_conversation_quota("public", ip, token)
        assert ok, f"should allow conversation #{i + 1}"
        store.start_or_get(None, ip, token, "public")
    ok, used, limit = store.check_conversation_quota("public", ip, token)
    assert not ok
    assert used == 3 and limit == 3


def test_session_store_turn_counter() -> None:
    store = SessionStore()
    state = store.start_or_get(None, "1.2.3.4", "", "public")
    for i in range(1, 11):
        ok, used, limit = store.check_turn_quota("public", state)
        assert ok, f"turn {i} should still be allowed"
        store.bump_turn(state.session_id)
    # 11th turn must be refused
    state = store.get(state.session_id)
    ok, used, limit = store.check_turn_quota("public", state)
    assert not ok
    assert used == 10 and limit == 10


def test_personal_tier_has_no_limit() -> None:
    store = SessionStore()
    ip, token = "1.2.3.4", "pers-xyz"
    # hammer 50 conversations — all should be allowed
    for _ in range(50):
        ok, *_ = store.check_conversation_quota("personal", ip, token)
        assert ok
        store.start_or_get(None, ip, token, "personal")


# Cloudflare Access JWT tests

@pytest.mark.asyncio
async def test_cf_access_missing_jwt_raises_401(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """CF JWT validation should reject requests without Cf-Access-Jwt-Assertion header."""
    from app.auth import cf_access_dep
    from unittest.mock import AsyncMock
    
    # Mock request without CF JWT header
    request = AsyncMock()
    request.headers.get.return_value = ""
    
    with pytest.raises(HTTPException) as exc:
        await cf_access_dep(request)
    
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_cf_access_dep_requires_valid_jwt(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """CF dependency should validate JWT format and signature."""
    from app.auth import cf_access_dep
    from unittest.mock import AsyncMock
    
    # Mock request with invalid JWT
    request = AsyncMock()
    request.headers.get.return_value = "invalid.jwt.token"
    
    with pytest.raises(HTTPException) as exc:
        await cf_access_dep(request)
    
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_cf_access_fallback_when_pyjwt_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """If pyjwt is not installed, CF validation should gracefully fallback."""
    from app.auth import validate_cf_jwt
    import builtins

    orig_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "jwt":
            raise ImportError("No module named 'jwt'")
        return orig_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    identity = await validate_cf_jwt("some-token")
    # Should return a fallback identity instead of raising
    assert identity.authenticated is True
    assert identity.email == "cf-verified@cloudflare"


def test_cf_access_identity_dataclass() -> None:
    """CFAccessIdentity should store email and identity_nonce."""
    from app.auth import CFAccessIdentity
    
    identity = CFAccessIdentity(
        email="user@example.com",
        identity_nonce="abc123",
        authenticated=True
    )
    
    assert identity.email == "user@example.com"
    assert identity.identity_nonce == "abc123"
    assert identity.authenticated is True
