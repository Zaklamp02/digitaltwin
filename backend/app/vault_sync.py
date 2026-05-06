"""Vault sync integration — bridges scripts/sync_vault.py into the app startup."""

from __future__ import annotations

import json
import logging
import subprocess
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

from .config import get_settings

log = logging.getLogger("ask-my-agent.vault-sync")


def _redact_remote(url: str) -> str:
    if not url:
        return ""
    if "@" in url and "://" in url:
        scheme, rest = url.split("://", 1)
        if "@" in rest:
            rest = rest.split("@", 1)[1]
        return f"{scheme}://***@{rest}"
    return url


def get_vault_sync_status() -> dict:
    settings = get_settings()
    vault_path = settings.vault_path
    vault_exists = vault_path is not None and vault_path.exists()
    git_enabled = bool(settings.vault_git_sync_enabled)
    git_ready = bool(vault_exists and (vault_path / ".git").exists()) if vault_path else False
    sync_available = vault_exists or (git_enabled and vault_path is not None and bool(settings.vault_git_remote_url))
    action_label = "Pull + Sync" if git_enabled else "Sync now"
    return {
        "vault_enabled": vault_exists,
        "vault_path": str(vault_path) if vault_path else None,
        "git_enabled": git_enabled,
        "git_ready": git_ready,
        "git_branch": settings.vault_git_branch if git_enabled else None,
        "git_remote": _redact_remote(settings.vault_git_remote_url) if git_enabled else None,
        "sync_available": sync_available,
        "action_label": action_label,
        "last_sync": get_last_sync_info(settings.knowledge_db_path),
    }


def prepare_vault_repo() -> dict | None:
    settings = get_settings()
    if not settings.vault_git_sync_enabled:
        return None

    vault_path = settings.vault_path
    if vault_path is None:
        raise RuntimeError("VAULT_DIR must be set when VAULT_GIT_SYNC_ENABLED=true")

    remote = settings.vault_git_remote_url.strip()
    branch = settings.vault_git_branch.strip() or "main"
    vault_path.parent.mkdir(parents=True, exist_ok=True)

    if (vault_path / ".git").exists():
        cmd = ["git", "-C", str(vault_path), "pull", "--ff-only", "origin", branch]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if proc.returncode != 0:
            raise RuntimeError((proc.stderr or proc.stdout or "git pull failed").strip())
        return {
            "git_action": "pull",
            "git_output": (proc.stdout or proc.stderr or "Already up to date.").strip(),
        }

    if not remote:
        raise RuntimeError("Vault repository is missing and VAULT_GIT_REMOTE_URL is not configured")

    cmd = ["git", "clone", "--branch", branch, "--single-branch", remote, str(vault_path)]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout or "git clone failed").strip())
    return {
        "git_action": "clone",
        "git_output": (proc.stdout or proc.stderr or "Repository cloned.").strip(),
    }


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
