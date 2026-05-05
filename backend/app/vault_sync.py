"""Vault sync integration — bridges scripts/sync_vault.py into the app startup."""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .knowledge import KnowledgeDB
    from .rag import RAGRetriever

# Reuse the sync pipeline from scripts/
import sys
_module_path = Path(__file__).resolve()
_script_candidates = [
    _module_path.parent.parent / "scripts",
    _module_path.parent.parent.parent / "scripts",
]
_scripts_dir = next((str(path) for path in _script_candidates if path.exists()), str(_script_candidates[0]))
if _scripts_dir not in sys.path:
    sys.path.insert(0, _scripts_dir)

from sync_vault import parse_vault, compute_diff, apply_diff, write_sync_log  # type: ignore[import-not-found]

log = logging.getLogger("ask-my-agent.vault-sync")


def sync_vault_to_db(vault_path: Path, knowledge: "KnowledgeDB",
                     retriever: "RAGRetriever | None" = None) -> dict:
    """Run a one-way sync from the Obsidian vault to the knowledge DB.

    If a retriever is provided, changed nodes are incrementally re-indexed
    in ChromaDB.

    Returns a summary dict with counts.
    """
    t0 = time.monotonic()

    vault_nodes, vault_edges, vault_settings = parse_vault(vault_path)
    log.info("vault sync: parsed %d nodes, %d edges from %s",
             len(vault_nodes), len(vault_edges), vault_path)

    # Compute diff against current DB state
    import sqlite3
    db = sqlite3.connect(str(knowledge.db_path), check_same_thread=False)
    db.execute("PRAGMA foreign_keys = ON")

    diff = compute_diff(vault_nodes, vault_edges, vault_settings, db)

    no_changes = (not diff.nodes_to_create and not diff.nodes_to_update and
                  not diff.nodes_to_delete and not diff.edges_to_create and
                  not diff.edges_to_delete and not diff.settings_to_update)

    if no_changes:
        log.info("vault sync: no changes detected")
        db.close()
        return {"status": "no_changes", "duration_s": round(time.monotonic() - t0, 2)}

    # Apply changes
    counts = apply_diff(diff, db)
    log.info("vault sync: created=%d updated=%d deleted=%d edges_created=%d edges_deleted=%d",
             counts["created"], counts["updated"], counts["deleted"],
             counts["edges_created"], counts["edges_deleted"])

    # Incremental ChromaDB reindex for changed nodes
    if retriever:
        changed_ids = {n.id for n in diff.nodes_to_create} | {n.id for n in diff.nodes_to_update}
        deleted_ids = set(diff.nodes_to_delete)

        for nid in deleted_ids:
            try:
                retriever.delete_node_from_index(nid)
            except Exception:
                pass

        for nid in changed_ids:
            node = knowledge.get_node(nid)
            if node and node.type != "system":
                # Only index non-personal nodes in ChromaDB for RAG
                roles = node.roles if hasattr(node, 'roles') else []
                if not any(r for r in roles if r != "personal"):
                    # Personal-only node — remove from index if it was there
                    try:
                        retriever.delete_node_from_index(nid)
                    except Exception:
                        pass
                else:
                    retriever.reindex_node(node)

        log.info("vault sync: re-indexed %d nodes in ChromaDB", len(changed_ids))

    duration = time.monotonic() - t0
    write_sync_log(knowledge.db_path, counts, duration)

    db.close()

    return {
        "status": "synced",
        "duration_s": round(duration, 2),
        **counts,
    }


def get_last_sync_info(knowledge_db_path: Path) -> dict | None:
    """Read the last sync log entry."""
    log_path = knowledge_db_path.parent / "vault_sync.log"
    if not log_path.exists():
        return None
    try:
        lines = log_path.read_text().strip().split("\n")
        if lines:
            return json.loads(lines[-1])
    except (json.JSONDecodeError, IndexError):
        pass
    return None
