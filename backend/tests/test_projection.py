"""Tests for public/internal runtime split and published dataset projection."""

from __future__ import annotations

from pathlib import Path

import app.main as main_module
import app.projection as projection_module

from app.config import Settings
from app.knowledge import KnowledgeDB
from app.projection import publish_projection


class FakeEmbedder:
    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[1.0, 0.0, 0.0] for _ in texts]


def test_create_app_omits_admin_routes_in_public_mode(monkeypatch) -> None:
    monkeypatch.setattr(main_module, "get_settings", lambda: Settings(app_mode="public"))

    app = main_module.create_app()
    paths = {route.path for route in app.routes}

    assert "/api/admin/stats" not in paths
    assert "/api/chat" in paths


def test_publish_projection_keeps_only_allowed_roles(tmp_path: Path, monkeypatch) -> None:
    source = KnowledgeDB(tmp_path / "internal.db")
    try:
        source.create_node(
            id="public-root",
            type="project",
            title="Public Root",
            body="Public body",
            roles=["public"],
        )
        source.create_node(
            id="public-child",
            type="project",
            title="Public Child",
            body="Public child body",
            roles=["public"],
        )
        source.create_node(
            id="private-child",
            type="personal",
            title="Private Child",
            body="Private body",
            roles=["personal"],
        )
        source.create_edge("public-root", "public-child", "includes", roles=["public"])
        source.create_edge("public-root", "private-child", "includes", roles=["personal"])
        source.set_setting("welcome_message", "hello")
    finally:
        source.close()

    monkeypatch.setattr(projection_module, "build_embedder", lambda settings: FakeEmbedder())

    counts = publish_projection(
        source_db_path=tmp_path / "internal.db",
        target_db_path=tmp_path / "public.db",
        target_chroma_path=tmp_path / "public-chroma",
        settings=Settings(
            openai_api_key="x",
            embedding_provider="openai",
            knowledge_db=str(tmp_path / "internal.db"),
            chroma_dir=str(tmp_path / "internal-chroma"),
        ),
        allowed_roles=["public"],
    )

    public = KnowledgeDB(tmp_path / "public.db")
    try:
        node_ids = {node.id for node in public.list_nodes()}
        edges = public.list_edges()

        assert counts.nodes == 2
        assert counts.edges == 1
        assert node_ids == {"public-root", "public-child"}
        assert len(edges) == 1
        assert edges[0].source_id == "public-root"
        assert edges[0].target_id == "public-child"
        assert public.get_setting("welcome_message") == "hello"
    finally:
        public.close()