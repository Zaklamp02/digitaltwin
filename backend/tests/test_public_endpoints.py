"""HTTP tests for public-facing endpoints with role-sensitive data exposure."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

import app.chat as chat_module
from app.auth import Caller, caller_dep
from app.chat import router as chat_router
from app.config import Settings
from app.knowledge import KnowledgeDB


def _make_settings(tmp_vault_dir: Path, tmp_path: Path) -> Settings:
    return Settings(
        credentials_file=str(tmp_path / "credentials.yaml"),
        vault_dir=str(tmp_vault_dir),
    )


@pytest.fixture
def public_app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> FastAPI:
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "image.png").write_bytes(b"\x89PNG\r\n\x1a\n")

    knowledge = KnowledgeDB(tmp_path / "knowledge.db")
    knowledge.create_node(
        id="public-node",
        type="project",
        title="Public Story",
        body="A public project overview.",
        roles=["public"],
    )
    knowledge.create_node(
        id="personal-node",
        type="personal",
        title="Private Journal",
        body="A private image note.",
        roles=["personal"],
        metadata={"image_path": "image.png"},
    )

    settings = _make_settings(vault, tmp_path)

    application = FastAPI()
    application.include_router(chat_router)
    application.dependency_overrides[chat_module.get_settings] = lambda: settings
    application.state.knowledge = knowledge
    return application


async def _get_json(application: FastAPI, path: str, caller: Caller) -> tuple[int, dict]:
    application.dependency_overrides[caller_dep] = lambda: caller
    async with AsyncClient(transport=ASGITransport(app=application), base_url="http://test") as client:
        response = await client.get(path)
    return response.status_code, response.json()


@pytest.mark.asyncio
async def test_suggestions_use_caller_roles(public_app: FastAPI) -> None:
    status, payload = await _get_json(
        public_app,
        "/api/suggestions",
        Caller(token="", tier="public", roles=["public"], label="anon", ip="10.0.0.1"),
    )

    assert status == 200
    suggestions = payload["suggestions"]
    assert suggestions
    assert not any("Private Journal" in suggestion for suggestion in suggestions)


@pytest.mark.asyncio
async def test_private_image_forbidden_for_public_caller(public_app: FastAPI) -> None:
    public_app.dependency_overrides[caller_dep] = lambda: Caller(
        token="",
        tier="public",
        roles=["public"],
        label="anon",
        ip="10.0.0.2",
    )

    async with AsyncClient(transport=ASGITransport(app=public_app), base_url="http://test") as client:
        response = await client.get("/api/content-image/image.png")

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_private_image_visible_to_personal_caller(public_app: FastAPI) -> None:
    public_app.dependency_overrides[caller_dep] = lambda: Caller(
        token="pers-xyz",
        tier="personal",
        roles=["public", "work", "friends", "personal"],
        label="owner",
        ip="10.0.0.3",
    )

    async with AsyncClient(transport=ASGITransport(app=public_app), base_url="http://test") as client:
        response = await client.get("/api/content-image/image.png")

    assert response.status_code == 200
    assert response.content.startswith(b"\x89PNG")