"""Vault sync integration — bridges scripts/sync_vault.py into the app startup."""

from __future__ import annotations

import json
import logging
import os
import shlex
import shutil
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

log = logging.getLogger("ask-my-agent.vault-sync")


def _run_git(vault_path: Path, args: list[str], timeout_s: int = 30) -> subprocess.CompletedProcess[str]:
    cmd = ["git", "-c", f"safe.directory={vault_path}", *args]

    # In NAS/container deployments we mount a dedicated deploy key as
    # /root/.ssh/notes_vault_deploy. Explicitly wire SSH so git fetch/pull
    # doesn't depend on default key names or ssh-agent state.
    env = os.environ.copy()
    ssh_parts = ["ssh", "-o", "BatchMode=yes", "-o", "IdentitiesOnly=yes"]

    key_path = Path(env.get("VAULT_GIT_SSH_KEY_PATH", "/root/.ssh/notes_vault_deploy"))
    if key_path.exists():
        ssh_parts.extend(["-i", str(key_path)])

    known_hosts_path = Path(env.get("VAULT_GIT_KNOWN_HOSTS_PATH", "/root/.ssh/known_hosts"))
    if known_hosts_path.exists():
        ssh_parts.extend(
            [
                "-o",
                f"UserKnownHostsFile={known_hosts_path}",
                "-o",
                "StrictHostKeyChecking=yes",
            ]
        )

    env["GIT_SSH_COMMAND"] = " ".join(shlex.quote(p) for p in ssh_parts)

    try:
        return subprocess.run(
            cmd,
            cwd=str(vault_path),
            text=True,
            capture_output=True,
            timeout=timeout_s,
            check=False,
            env=env,
        )
    except subprocess.TimeoutExpired as e:
        return subprocess.CompletedProcess(
            args=cmd,
            returncode=124,
            stdout=e.stdout or "",
            stderr=(e.stderr or "") + f"\nCommand timed out after {timeout_s}s",
        )


def get_vault_git_status(vault_path: Path | None) -> dict:
    """Return git availability/status metadata for a vault path."""
    base = {
        "git_available": shutil.which("git") is not None,
        "git_ready": False,
        "git_branch": None,
        "git_remote": None,
        "git_error": None,
    }
    if vault_path is None:
        base["git_error"] = "vault_not_configured"
        return base
    if not base["git_available"]:
        base["git_error"] = "git_not_installed"
        return base

    probe = _run_git(vault_path, ["rev-parse", "--is-inside-work-tree"])
    if probe.returncode != 0 or probe.stdout.strip() != "true":
        base["git_error"] = "not_a_git_repo"
        return base

    branch = _run_git(vault_path, ["rev-parse", "--abbrev-ref", "HEAD"])
    remote = _run_git(vault_path, ["config", "--get", "remote.origin.url"])

    base["git_ready"] = True
    base["git_branch"] = branch.stdout.strip() or None
    base["git_remote"] = remote.stdout.strip() or None
    return base


def pull_vault_repo(vault_path: Path, remote: str = "origin", branch: str = "") -> dict:
    """Run git pull in the vault repo and report whether HEAD changed."""
    status = get_vault_git_status(vault_path)
    if not status.get("git_ready"):
        return {
            "attempted": False,
            "ok": False,
            "changed": False,
            "reason": status.get("git_error") or "git_not_ready",
            **status,
        }

    before = _run_git(vault_path, ["rev-parse", "HEAD"])
    before_sha = before.stdout.strip() if before.returncode == 0 else ""

    target_branch = branch
    if not target_branch:
        current = _run_git(vault_path, ["rev-parse", "--abbrev-ref", "HEAD"])
        target_branch = current.stdout.strip() if current.returncode == 0 else "main"

    fetch = _run_git(vault_path, ["fetch", remote, target_branch], timeout_s=90)
    if fetch.returncode != 0:
        return {
            "attempted": True,
            "ok": False,
            "changed": False,
            "reason": fetch.stderr.strip() or "fetch_failed",
            "stdout": fetch.stdout.strip(),
            "stderr": fetch.stderr.strip(),
            **status,
        }

    # Source of truth is remote git state: force local worktree to fetched HEAD.
    reset = _run_git(vault_path, ["reset", "--hard", "FETCH_HEAD"], timeout_s=60)
    clean = _run_git(vault_path, ["clean", "-fd"], timeout_s=60)

    result_ok = reset.returncode == 0 and clean.returncode == 0
    result_stdout = "\n".join(p for p in [fetch.stdout.strip(), reset.stdout.strip(), clean.stdout.strip()] if p)
    result_stderr = "\n".join(p for p in [fetch.stderr.strip(), reset.stderr.strip(), clean.stderr.strip()] if p)

    after = _run_git(vault_path, ["rev-parse", "HEAD"])
    after_sha = after.stdout.strip() if after.returncode == 0 else ""

    return {
        "attempted": True,
        "ok": result_ok,
        "changed": bool(before_sha and after_sha and before_sha != after_sha),
        "before": before_sha,
        "after": after_sha,
        "stdout": result_stdout,
        "stderr": result_stderr,
        **status,
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
