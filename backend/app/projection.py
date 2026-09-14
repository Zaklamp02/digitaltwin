"""Build reduced published datasets from the internal knowledge database."""

from __future__ import annotations

import shutil
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from .config import Settings
from .knowledge import KnowledgeDB
from .rag import RAGRetriever, build_embedder


@dataclass(frozen=True)
class ProjectionCounts:
    nodes: int
    edges: int
    indexed_nodes: int


def _clear_directory_contents(path: Path) -> None:
    """Remove all children under a directory without removing the directory itself.

    This is mount-point safe: removing a bind-mounted directory root can raise
    EBUSY on NAS/container setups.
    """
    if not path.exists():
        path.mkdir(parents=True, exist_ok=True)
        return

    for child in path.iterdir():
        if child.is_dir() and not child.is_symlink():
            shutil.rmtree(child)
        else:
            child.unlink(missing_ok=True)


def _reset_projection_db(path: Path) -> None:
    """Clear projection tables in-place to avoid replacing the DB file path.

    Keeping the same file path/inode minimizes disruption for long-lived readers.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    try:
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute("CREATE TABLE IF NOT EXISTS nodes (id TEXT PRIMARY KEY)")
        conn.execute("CREATE TABLE IF NOT EXISTS edges (id TEXT PRIMARY KEY)")
        conn.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY)")
        conn.execute("DELETE FROM edges")
        conn.execute("DELETE FROM nodes")
        conn.execute("DELETE FROM settings")
        conn.commit()
    finally:
        conn.close()


def publish_projection(
    source_db_path: Path,
    target_db_path: Path,
    target_chroma_path: Path,
    settings: Settings,
    allowed_roles: list[str],
    reindex_vectors: bool = True,
) -> ProjectionCounts:
    """Create a published dataset containing only nodes/edges matching allowed roles."""
    source = KnowledgeDB(source_db_path)
    try:
        _reset_projection_db(target_db_path)
        if reindex_vectors:
            # target_chroma_path can be a bind-mounted directory root on NAS.
            # Clearing children avoids EBUSY from removing the mount point itself.
            _clear_directory_contents(target_chroma_path)
        target_chroma_path.parent.mkdir(parents=True, exist_ok=True)

        target = KnowledgeDB(target_db_path)
        try:
            role_set = set(allowed_roles)
            nodes = [
                node for node in source.list_nodes(role_filter=None)
                if role_set.intersection(set(node.roles))
            ]
            node_ids = {node.id for node in nodes}
            edges = [
                edge for edge in source.list_edges()
                if role_set.intersection(set(edge.roles))
                and edge.source_id in node_ids
                and edge.target_id in node_ids
            ]

            for node in nodes:
                target.create_node(
                    id=node.id,
                    type=node.type,
                    title=node.title,
                    body=node.body,
                    metadata=node.metadata,
                    roles=node.roles,
                )
            for edge in edges:
                target.create_edge(
                    source_id=edge.source_id,
                    target_id=edge.target_id,
                    type=edge.type,
                    label=edge.label,
                    roles=edge.roles,
                )

            for key in ("welcome_message", "suggestion_chips", "translation_prompt"):
                value = source.get_setting(key)
                if value is not None:
                    target.set_setting(key, value)

            indexed_nodes = 0
            if reindex_vectors:
                projection_settings = settings.model_copy(
                    update={
                        "knowledge_db": str(target_db_path),
                        "chroma_dir": str(target_chroma_path),
                        "app_mode": "public",
                    }
                )
                retriever = RAGRetriever(
                    settings=projection_settings,
                    knowledge=target,
                    embedder=build_embedder(projection_settings),
                )
                indexed_nodes = retriever.reindex_all()
            return ProjectionCounts(nodes=len(nodes), edges=len(edges), indexed_nodes=indexed_nodes)
        finally:
            target.close()
    finally:
        source.close()