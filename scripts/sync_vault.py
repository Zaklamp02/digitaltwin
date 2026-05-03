#!/usr/bin/env python3
"""Sync an Obsidian vault → SQLite knowledge.db + ChromaDB.

Usage:
    python scripts/sync_vault.py [--vault ~/ObsidianVault/digital-twin] [--db data/knowledge.db] [--full]

Reads all .md files from the vault, parses YAML frontmatter, resolves
wikilinks and folder hierarchy, then upserts into the SQLite database.
Optionally re-embeds changed nodes into ChromaDB.

This is a ONE-WAY sync: the vault always wins.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import re
import sqlite3
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

log = logging.getLogger("vault-sync")

# ── data classes ───────────────────────────────────────────────────────

@dataclass
class VaultNode:
    """A node parsed from a vault .md file."""
    id: str
    type: str
    title: str
    body: str
    roles: list[str] = field(default_factory=lambda: ["public"])
    metadata: dict[str, Any] = field(default_factory=dict)
    source_path: str = ""           # relative path within vault
    content_hash: str = ""          # hash of body + frontmatter for change detection

@dataclass
class VaultEdge:
    """An edge derived from the vault structure."""
    source_id: str
    target_id: str
    type: str
    label: str = ""


# ── vault parser ───────────────────────────────────────────────────────

FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?", re.DOTALL)
WIKILINK_RE = re.compile(r"\[\[([^\]]+)\]\]")

# Frontmatter keys that map to promoted node fields (not stored in metadata)
NODE_FIELDS = {"type", "id", "title", "roles", "links"}
# Metadata keys to promote to top-level metadata dict
META_KEYS = {"featured", "icon", "order", "notebook_root", "url",
             "file", "original_filename", "mime_type", "extra_files", "extra_meta"}

CONTAINMENT_EDGE_TYPES = {"has", "includes", "nb_page"}

# Default roles if not specified
DEFAULT_ROLES = ["public"]


def _parse_frontmatter(content: str) -> tuple[dict, str]:
    """Parse YAML frontmatter from markdown content.

    Returns (frontmatter_dict, body_without_frontmatter).
    """
    m = FRONTMATTER_RE.match(content)
    if not m:
        return {}, content

    try:
        fm = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError as e:
        log.warning("Bad YAML frontmatter: %s", e)
        return {}, content

    body = content[m.end():]
    return fm, body


def _resolve_wikilinks(fm_links: dict, filename_to_id: dict[str, str]) -> list[VaultEdge]:
    """Resolve frontmatter links: {edge_type: "[[target]]" or ["[[t1]]", "[[t2]]"]}."""
    edges = []
    for edge_type, targets in fm_links.items():
        if isinstance(targets, str):
            targets = [targets]
        for t in targets:
            # Extract wikilink name
            m = WIKILINK_RE.search(str(t))
            if m:
                link_name = m.group(1).strip()
                # Resolve to node ID
                target_id = filename_to_id.get(link_name)
                if target_id:
                    edges.append(VaultEdge(source_id="", target_id=target_id, type=edge_type))
                else:
                    log.warning("Unresolved wikilink: [[%s]]", link_name)
    return edges


def _content_hash(frontmatter: dict, body: str) -> str:
    """Hash the content for change detection."""
    h = hashlib.sha256()
    h.update(json.dumps(frontmatter, sort_keys=True, default=str).encode())
    h.update(body.encode())
    return h.hexdigest()[:16]


def _id_from_path(rel_path: str) -> str:
    """Derive a node ID from a relative vault path.

    Examples:
        work/career/_index.md → career
        work/experience--youwe/clients/projects--pricing-engine.md → projects--pricing-engine
        _index.md → identity (root)
    """
    p = Path(rel_path)
    stem = p.stem
    if stem == "_index":
        # Use the parent directory name as the ID
        return p.parent.name if p.parent.name else "identity"
    return stem


def parse_vault(vault_path: Path) -> tuple[list[VaultNode], list[VaultEdge], dict]:
    """Parse all .md files in the vault into nodes and edges.

    Returns (nodes, edges, settings_from_config).
    """
    nodes: list[VaultNode] = []
    edges: list[VaultEdge] = []
    settings: dict = {}

    # Collect all .md files (skip .obsidian, documents)
    md_files: list[Path] = []
    for f in sorted(vault_path.rglob("*.md")):
        rel = f.relative_to(vault_path)
        # Skip hidden dirs, documents, etc.
        if any(part.startswith(".") for part in rel.parts):
            continue
        md_files.append(f)

    # First pass: build filename → node_id mapping for wikilink resolution
    filename_to_id: dict[str, str] = {}
    file_node_ids: dict[str, str] = {}  # rel_path → node_id

    for f in md_files:
        rel = str(f.relative_to(vault_path))
        if f.name in ("_system.md", "_config.md"):
            continue

        content = f.read_text(encoding="utf-8")
        fm, _ = _parse_frontmatter(content)

        # ID from frontmatter takes precedence, then derive from path
        node_id = fm.get("id") or _id_from_path(rel)
        filename_to_id[f.stem] = node_id
        # Also map the slug (for wikilinks that reference by slug)
        filename_to_id[_id_from_path(rel)] = node_id
        # Also map the frontmatter ID itself (e.g. "nb-work" for _index.md files)
        if fm.get("id"):
            filename_to_id[fm["id"]] = node_id
        # Also map the node_id (for self-referencing resolution)
        filename_to_id[node_id] = node_id
        file_node_ids[rel] = node_id

    # Second pass: parse all files into nodes and edges
    for f in md_files:
        rel = str(f.relative_to(vault_path))
        content = f.read_text(encoding="utf-8")
        fm, body = _parse_frontmatter(content)

        # Handle special files
        if f.name == "_system.md":
            # System prompt — just the body, no frontmatter
            nodes.append(VaultNode(
                id="_system",
                type="system",
                title="System prompt — Sebastiaan's Digital Twin",
                body=body.strip(),
                roles=["personal"],
                source_path=rel,
                content_hash=_content_hash({}, body),
            ))
            continue

        if f.name == "_config.md":
            # Website config — extract settings from frontmatter
            for key in ("welcome_message", "suggestion_chips", "translation_prompt"):
                if key in fm:
                    val = fm[key]
                    settings[key] = json.dumps(val) if isinstance(val, (list, dict)) else str(val)
            continue

        # Regular node
        node_id = fm.get("id") or _id_from_path(rel)
        node_type = fm.get("type", "document")
        title = fm.get("title", f.stem.replace("-", " ").replace("_", " ").title())
        roles = fm.get("roles", DEFAULT_ROLES)
        if not roles:
            roles = DEFAULT_ROLES

        # Build metadata from promoted keys
        metadata: dict[str, Any] = {}
        for key in META_KEYS:
            if key in fm:
                if key == "extra_meta":
                    # Merge extra_meta contents into metadata
                    extra = fm[key]
                    if isinstance(extra, str):
                        try:
                            extra = json.loads(extra)
                        except json.JSONDecodeError:
                            pass
                    if isinstance(extra, dict):
                        metadata.update(extra)
                elif key == "file":
                    metadata["file_path"] = fm[key]
                else:
                    metadata[key] = fm[key]

        node = VaultNode(
            id=node_id,
            type=node_type,
            title=title,
            body=body.strip(),
            roles=roles,
            metadata=metadata,
            source_path=rel,
            content_hash=_content_hash(fm, body),
        )
        nodes.append(node)

        # Resolve cross-link edges from frontmatter
        if "links" in fm and isinstance(fm["links"], dict):
            link_edges = _resolve_wikilinks(fm["links"], filename_to_id)
            for edge in link_edges:
                edge.source_id = node_id
                edges.append(edge)

    # Third pass: infer containment edges from folder hierarchy
    # A file inside a folder is a child of the folder's _index node
    for f in md_files:
        rel = str(f.relative_to(vault_path))
        if f.name in ("_system.md", "_config.md"):
            continue

        node_id = file_node_ids.get(rel)
        if not node_id:
            continue

        # For _index.md files, the node IS the folder.
        # Its parent is the _index.md in the grandparent directory.
        if f.name == "_index.md":
            grandparent = f.parent.parent
            if grandparent == vault_path or f.parent == vault_path:
                # Top-level _index.md or one level deep — child of identity
                if node_id != "identity":
                    edges.append(VaultEdge(
                        source_id="identity",
                        target_id=node_id,
                        type="includes",
                    ))
            else:
                parent_index = grandparent / "_index.md"
                parent_rel = str(parent_index.relative_to(vault_path))
                parent_id = file_node_ids.get(parent_rel)
                if parent_id and parent_id != node_id:
                    edges.append(VaultEdge(
                        source_id=parent_id,
                        target_id=node_id,
                        type="includes",
                    ))
        else:
            # Regular file — parent is the _index.md in the same directory
            parent_dir = f.parent
            if parent_dir == vault_path:
                # Top-level file — child of root (identity)
                if node_id != "identity":
                    edges.append(VaultEdge(
                        source_id="identity",
                        target_id=node_id,
                        type="includes",
                    ))
            else:
                parent_index = parent_dir / "_index.md"
                parent_rel = str(parent_index.relative_to(vault_path))
                parent_id = file_node_ids.get(parent_rel)
                if parent_id and parent_id != node_id:
                    edges.append(VaultEdge(
                        source_id=parent_id,
                        target_id=node_id,
                        type="includes",
                    ))

    return nodes, edges, settings


# ── diff engine ────────────────────────────────────────────────────────

@dataclass
class SyncDiff:
    nodes_to_create: list[VaultNode] = field(default_factory=list)
    nodes_to_update: list[VaultNode] = field(default_factory=list)
    nodes_to_delete: list[str] = field(default_factory=list)
    edges_to_create: list[VaultEdge] = field(default_factory=list)
    edges_to_delete: list[str] = field(default_factory=list)  # edge IDs
    settings_to_update: dict[str, str] = field(default_factory=dict)


def compute_diff(vault_nodes: list[VaultNode], vault_edges: list[VaultEdge],
                 vault_settings: dict, db: sqlite3.Connection) -> SyncDiff:
    """Compare vault state with DB state and produce a changeset."""
    diff = SyncDiff()

    # Load current DB nodes
    db.row_factory = sqlite3.Row
    db_nodes: dict[str, dict] = {}
    for r in db.execute("SELECT id, type, title, body, metadata, roles, created_at, updated_at FROM nodes"):
        db_nodes[r["id"]] = dict(r)

    # Load current DB edges
    db_edges: dict[str, dict] = {}
    for r in db.execute("SELECT id, source_id, target_id, type, label FROM edges"):
        db_edges[r["id"]] = dict(r)

    # Vault node IDs
    vault_node_ids = {n.id for n in vault_nodes}

    # Nodes to create or update
    for vn in vault_nodes:
        if vn.id not in db_nodes:
            diff.nodes_to_create.append(vn)
        else:
            # Check if content changed
            db_n = db_nodes[vn.id]
            db_body = (db_n["body"] or "").strip()
            db_roles = _safe_json(db_n["roles"], ["public"])
            db_meta = _safe_json(db_n["metadata"], {})

            changed = False
            if vn.body.strip() != db_body:
                changed = True
            if vn.title != db_n["title"]:
                changed = True
            if vn.type != db_n["type"]:
                changed = True
            if sorted(vn.roles) != sorted(db_roles):
                changed = True
            # Check metadata changes (ignore body_blocks and source_file)
            clean_db_meta = {k: v for k, v in db_meta.items()
                           if k not in ("body_blocks", "source_file")}
            if vn.metadata != clean_db_meta:
                changed = True

            if changed:
                diff.nodes_to_update.append(vn)

    # Nodes to delete (in DB but not in vault)
    for db_id in db_nodes:
        if db_id not in vault_node_ids:
            diff.nodes_to_delete.append(db_id)

    # Edges: rebuild from scratch (simpler and correct)
    # Build the set of desired edges
    desired_edges: set[tuple[str, str, str]] = set()  # (source, target, type)
    for ve in vault_edges:
        desired_edges.add((ve.source_id, ve.target_id, ve.type))

    # Edges to create
    existing_edges: set[tuple[str, str, str]] = set()
    for eid, e in db_edges.items():
        key = (e["source_id"], e["target_id"], e["type"])
        existing_edges.add(key)

    for ve in vault_edges:
        key = (ve.source_id, ve.target_id, ve.type)
        if key not in existing_edges:
            diff.edges_to_create.append(ve)

    # Edges to delete
    for eid, e in db_edges.items():
        key = (e["source_id"], e["target_id"], e["type"])
        if key not in desired_edges:
            diff.edges_to_delete.append(eid)

    # Settings
    diff.settings_to_update = vault_settings

    return diff


def _safe_json(val, default):
    if not val or not str(val).strip():
        return default
    try:
        return json.loads(val) if isinstance(val, str) else val
    except (json.JSONDecodeError, TypeError):
        return default


# ── DB writer ──────────────────────────────────────────────────────────

def apply_diff(diff: SyncDiff, db: sqlite3.Connection) -> dict[str, int]:
    """Apply the sync diff to the database. Returns counts."""
    now = datetime.now(timezone.utc).isoformat()
    counts = {"created": 0, "updated": 0, "deleted": 0,
              "edges_created": 0, "edges_deleted": 0, "settings": 0}

    with db:
        # Delete nodes
        for node_id in diff.nodes_to_delete:
            db.execute("DELETE FROM nodes WHERE id = ?", (node_id,))
            counts["deleted"] += 1

        # Create nodes
        for n in diff.nodes_to_create:
            db.execute("""
                INSERT INTO nodes (id, type, title, body, metadata, roles, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (n.id, n.type, n.title, n.body,
                  json.dumps(n.metadata), json.dumps(n.roles), now, now))
            counts["created"] += 1

        # Update nodes
        for n in diff.nodes_to_update:
            db.execute("""
                UPDATE nodes SET type=?, title=?, body=?, metadata=?, roles=?, updated_at=?
                WHERE id=?
            """, (n.type, n.title, n.body,
                  json.dumps(n.metadata), json.dumps(n.roles), now, n.id))
            counts["updated"] += 1

        # Delete edges
        for eid in diff.edges_to_delete:
            db.execute("DELETE FROM edges WHERE id = ?", (eid,))
            counts["edges_deleted"] += 1

        # Create edges
        for e in diff.edges_to_create:
            eid = hashlib.sha256(f"{e.source_id}:{e.target_id}:{e.type}".encode()).hexdigest()[:16]
            try:
                db.execute("""
                    INSERT INTO edges (id, source_id, target_id, type, label, roles, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (eid, e.source_id, e.target_id, e.type, e.label,
                      json.dumps([]), now))
                counts["edges_created"] += 1
            except sqlite3.IntegrityError:
                # Edge already exists (unique constraint) — skip
                log.debug("edge already exists: %s → %s (%s)", e.source_id, e.target_id, e.type)

        # Settings
        for key, value in diff.settings_to_update.items():
            db.execute("""
                INSERT INTO settings (key, value, updated_at) VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
            """, (key, value, now))
            counts["settings"] += 1

    return counts


# ── ChromaDB incremental reindex ───────────────────────────────────────

def reindex_changed_nodes(diff: SyncDiff, db: sqlite3.Connection,
                          chroma_path: str, embedding_provider: str = "openai",
                          openai_api_key: str = "") -> int:
    """Re-embed only the nodes that changed. Returns chunk count."""
    # Import backend modules
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
    from app.indexer import chunk_node, upsert_chunks, delete_node_chunks
    from app.knowledge import KnowledgeNode
    from app.embedders import OpenAIEmbedder, LocalEmbedder

    import chromadb

    client = chromadb.PersistentClient(path=chroma_path)
    collection = client.get_or_create_collection(
        name="memory_palace",
        metadata={"hnsw:space": "cosine"},
    )

    # Build embedder
    if embedding_provider == "openai" and openai_api_key:
        embedder = OpenAIEmbedder(api_key=openai_api_key)
    else:
        embedder = LocalEmbedder()

    total_chunks = 0
    changed_ids = {n.id for n in diff.nodes_to_create} | {n.id for n in diff.nodes_to_update}
    deleted_ids = set(diff.nodes_to_delete)

    # Delete chunks for removed/changed nodes
    for nid in deleted_ids | changed_ids:
        try:
            delete_node_chunks(collection, nid)
        except Exception:
            pass

    # Re-embed changed/new nodes
    db.row_factory = sqlite3.Row
    for nid in changed_ids:
        row = db.execute("SELECT * FROM nodes WHERE id = ?", (nid,)).fetchone()
        if not row or row["type"] == "system":
            continue
        node = KnowledgeNode(
            id=row["id"],
            type=row["type"],
            title=row["title"],
            body=row["body"] or "",
            metadata=_safe_json(row["metadata"], {}),
            roles=_safe_json(row["roles"], ["public"]),
            created_at=row["created_at"] or "",
            updated_at=row["updated_at"] or "",
        )
        chunks = chunk_node(node, chunk_tokens=300, overlap=50)
        upsert_chunks(collection, embedder, chunks)
        total_chunks += len(chunks)

    return total_chunks


# ── sync log ───────────────────────────────────────────────────────────

SYNC_LOG_FILE = "vault_sync.log"


def write_sync_log(db_path: Path, counts: dict, duration: float):
    """Append a summary line to the sync log."""
    log_path = db_path.parent / SYNC_LOG_FILE
    now = datetime.now(timezone.utc).isoformat()
    entry = {
        "timestamp": now,
        "duration_s": round(duration, 2),
        **counts,
    }
    with open(log_path, "a") as f:
        f.write(json.dumps(entry) + "\n")


# ── main ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Sync Obsidian vault → SQLite + ChromaDB")
    parser.add_argument("--vault", default=str(Path.home() / "ObsidianVault" / "digital-twin"),
                        help="Path to Obsidian vault")
    parser.add_argument("--db", default="data/knowledge.db",
                        help="Path to knowledge.db")
    parser.add_argument("--chroma", default="chroma_db",
                        help="Path to ChromaDB directory")
    parser.add_argument("--full", action="store_true",
                        help="Full reindex (wipe and rebuild ChromaDB)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would change without writing")
    parser.add_argument("--no-embed", action="store_true",
                        help="Skip ChromaDB embedding (SQLite only)")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s: %(message)s",
    )

    vault_path = Path(args.vault)
    db_path = Path(args.db)

    if not vault_path.exists():
        log.error("Vault not found: %s", vault_path)
        return 1

    # Parse vault
    log.info("📖 Parsing vault: %s", vault_path)
    t0 = time.monotonic()
    vault_nodes, vault_edges, vault_settings = parse_vault(vault_path)
    log.info("   %d nodes, %d edges, %d settings parsed",
             len(vault_nodes), len(vault_edges), len(vault_settings))

    # Open DB
    if not db_path.exists():
        log.info("   Creating new database: %s", db_path)
        db_path.parent.mkdir(parents=True, exist_ok=True)

    db = sqlite3.connect(str(db_path))
    db.execute("PRAGMA foreign_keys = ON")
    db.execute("PRAGMA journal_mode = WAL")
    # Ensure tables exist
    db.executescript("""
        CREATE TABLE IF NOT EXISTS nodes (
            id TEXT PRIMARY KEY,
            type TEXT NOT NULL,
            title TEXT NOT NULL,
            body TEXT,
            metadata TEXT DEFAULT '{}',
            roles TEXT DEFAULT '["public"]',
            created_at TEXT,
            updated_at TEXT
        );
        CREATE TABLE IF NOT EXISTS edges (
            id TEXT PRIMARY KEY,
            source_id TEXT NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
            target_id TEXT NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
            type TEXT NOT NULL,
            label TEXT DEFAULT '',
            roles TEXT DEFAULT '[]',
            created_at TEXT,
            UNIQUE(source_id, target_id, type)
        );
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT,
            updated_at TEXT
        );
        CREATE TABLE IF NOT EXISTS translations (
            key TEXT PRIMARY KEY,
            source_en TEXT,
            source_hash TEXT,
            text_nl TEXT,
            is_manual INTEGER DEFAULT 0,
            stale INTEGER DEFAULT 0,
            updated_at TEXT
        );
        CREATE TABLE IF NOT EXISTS deleted_seed_edges (
            id TEXT PRIMARY KEY
        );
    """)

    # Compute diff
    diff = compute_diff(vault_nodes, vault_edges, vault_settings, db)

    # Report
    log.info("\n📊 Diff summary:")
    log.info("   Nodes to create: %d", len(diff.nodes_to_create))
    log.info("   Nodes to update: %d", len(diff.nodes_to_update))
    log.info("   Nodes to delete: %d", len(diff.nodes_to_delete))
    log.info("   Edges to create: %d", len(diff.edges_to_create))
    log.info("   Edges to delete: %d", len(diff.edges_to_delete))
    log.info("   Settings to set: %d", len(diff.settings_to_update))

    if diff.nodes_to_create:
        for n in diff.nodes_to_create:
            log.info("   + %s (%s)", n.id, n.type)
    if diff.nodes_to_update:
        for n in diff.nodes_to_update:
            log.info("   ~ %s (%s)", n.id, n.type)
    if diff.nodes_to_delete:
        for nid in diff.nodes_to_delete:
            log.info("   - %s", nid)

    if args.dry_run:
        log.info("\n🔍 Dry run — no changes written")
        return 0

    no_changes = (not diff.nodes_to_create and not diff.nodes_to_update and
                  not diff.nodes_to_delete and not diff.edges_to_create and
                  not diff.edges_to_delete and not diff.settings_to_update)

    if no_changes and not args.full:
        log.info("\n✅ No changes detected — vault and DB are in sync")
        return 0

    # Apply diff
    log.info("\n💾 Applying changes to: %s", db_path)
    counts = apply_diff(diff, db)
    log.info("   Created: %d, Updated: %d, Deleted: %d", counts["created"], counts["updated"], counts["deleted"])
    log.info("   Edges created: %d, Edges deleted: %d", counts["edges_created"], counts["edges_deleted"])

    # ChromaDB reindex
    if not args.no_embed and (diff.nodes_to_create or diff.nodes_to_update or
                               diff.nodes_to_delete or args.full):
        chroma_path = str(Path(args.chroma).resolve())
        openai_key = os.environ.get("OPENAI_API_KEY", "")
        embedding_provider = os.environ.get("EMBEDDING_PROVIDER", "openai")

        if args.full:
            log.info("\n🔄 Full ChromaDB reindex...")
            # For full reindex, mark all nodes as "created" to re-embed everything
            all_nodes = vault_nodes[:]
            diff_full = SyncDiff(nodes_to_create=all_nodes)
            n_chunks = reindex_changed_nodes(diff_full, db, chroma_path,
                                             embedding_provider, openai_key)
        else:
            log.info("\n📡 Incremental ChromaDB reindex...")
            n_chunks = reindex_changed_nodes(diff, db, chroma_path,
                                             embedding_provider, openai_key)
        log.info("   %d chunks embedded", n_chunks)
        counts["chunks_embedded"] = n_chunks

    duration = time.monotonic() - t0
    write_sync_log(db_path, counts, duration)
    log.info("\n✅ Sync complete in %.1fs", duration)

    db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
