"""Auth + rate-limit tests."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from app.config import accessible_tiers, load_tokens
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
