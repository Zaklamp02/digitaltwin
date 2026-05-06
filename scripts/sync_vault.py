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
from datetime import date, datetime, timezone
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
    roles: list[str] = field(default_factory=lambda: ["personal"])
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
WIKILINK_RE = re.compile(r"\[\[([^\]|]+)(?:\|[^\]]*)?\]\]")

# Frontmatter keys that map to promoted node fields (not stored in metadata)
NODE_FIELDS = {"visibility", "parent", "secondary_parents"}
# Metadata keys to promote to top-level metadata dict
META_KEYS = {"featured", "icon", "notebook_root", "url", "date", "tags",
             "file", "original_filename", "mime_type", "extra_files", "extra_meta"}

CONTAINMENT_EDGE_TYPES = {"includes"}

# Default visibility → roles mapping
DEFAULT_VISIBILITY = "personal"  # not indexed for RAG by default


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


def _resolve_body_wikilinks(
    body: str,
    source_id: str,
    filename_to_id: dict[str, str],
    document_files: dict[str, str] | None = None,
) -> tuple[list[VaultEdge], list[str]]:
    """Extract [[wikilinks]] from body text and create relates_to edges.

    Returns (edges, attached_document_paths).
    """
    edges = []
    doc_paths: list[str] = []
    seen = set()
    for m in WIKILINK_RE.finditer(body):
        link_name = m.group(1).strip()
        if link_name in seen:
            continue
        seen.add(link_name)
        target_id = filename_to_id.get(link_name)
        if target_id and target_id != source_id:
            edges.append(VaultEdge(source_id=source_id, target_id=target_id, type="relates_to"))
        elif document_files and link_name in document_files:
            doc_paths.append(document_files[link_name])
        elif not target_id:
            log.warning("Unresolved wikilink: [[%s]] in %s", link_name, source_id)
    return edges, doc_paths


def _content_hash(frontmatter: dict, body: str) -> str:
    """Hash the content for change detection."""
    # Exclude managed keys (injected by sync) from hash to avoid false diffs
    fm_clean = {k: v for k, v in frontmatter.items() if k != MANAGED_FM_KEY}
    h = hashlib.sha256()
    h.update(json.dumps(fm_clean, sort_keys=True, default=str).encode())
    h.update(body.encode())
    return h.hexdigest()[:16]


def _id_from_path(rel_path: str, vault_name: str = "") -> str:
    """Derive a node ID from a relative vault path.

    For folder notes (filename matches parent folder), uses the stem.
    For regular files, uses the filename stem.

    Examples:
        education/education.md → education
        work/career/philips.md → philips
        digital-twin.md → digital-twin
    """
    return Path(rel_path).stem


def _is_folder_note(f: Path) -> bool:
    """Check if a file is a folder note (filename matches parent folder name)."""
    return f.stem == f.parent.name


def _title_from_stem(stem: str) -> str:
    """Derive a human-readable title from a filename stem.

    Preserves the original casing of the stem; only replaces
    hyphens/underscores with spaces so that acronyms like ACE or
    BIG4 are not mangled by str.title().
    """
    return stem.replace("-", " ").replace("_", " ")


def _parse_secondary_parents(value: Any) -> list[str]:
    """Normalize secondary_parents frontmatter into a list of note titles."""
    if value is None:
        return []
    if isinstance(value, str):
        values = [value]
    elif isinstance(value, list):
        values = value
    else:
        return []

    parents: list[str] = []
    seen: set[str] = set()
    for item in values:
        if item is None:
            continue
        text = str(item).strip()
        if not text:
            continue
        match = WIKILINK_RE.search(text)
        target = match.group(1).strip() if match else text
        if target not in seen:
            parents.append(target)
            seen.add(target)
    return parents


def parse_vault(vault_path: Path) -> tuple[list[VaultNode], list[VaultEdge], dict]:
    """Parse all .md files in the vault into nodes and edges.

    Returns (nodes, edges, settings_from_config).
    """
    nodes: list[VaultNode] = []
    edges: list[VaultEdge] = []
    settings: dict = {}

    # Collect all .md files (skip .obsidian, templates, documents)
    md_files: list[Path] = []
    for f in sorted(vault_path.rglob("*.md")):
        rel = f.relative_to(vault_path)
        # Skip hidden dirs, templates
        if any(part.startswith(".") for part in rel.parts):
            continue
        if rel.parts and rel.parts[0] == "templates":
            continue
        md_files.append(f)

    # First pass: build filename → node_id mapping for wikilink resolution
    filename_to_id: dict[str, str] = {}
    file_node_ids: dict[str, str] = {}  # rel_path → node_id

    for f in md_files:
        rel = str(f.relative_to(vault_path))
        if f.name in ("_system.md", "_config.md"):
            continue

        vault_name = vault_path.name
        node_id = _id_from_path(rel, vault_name)
        filename_to_id[f.stem] = node_id
        file_node_ids[rel] = node_id

    # Build document/attachment filename map (for resolving [[file.pdf]] links)
    document_files: dict[str, str] = {}  # stem-or-full-name → relative path
    docs_dir = vault_path / "documents"
    if docs_dir.is_dir():
        for df in docs_dir.iterdir():
            if df.is_file() and not df.name.startswith("."):
                rel_path = str(df.relative_to(vault_path))
                document_files[df.stem] = rel_path
                document_files[df.name] = rel_path  # also match with extension

    # Second pass: parse all files into nodes and edges
    for f in md_files:
        rel = str(f.relative_to(vault_path))
        content = f.read_text(encoding="utf-8")
        fm, body = _parse_frontmatter(content)

        # Handle special files
        if f.name == "_system.md":
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
            for key in ("welcome_message", "suggestion_chips", "translation_prompt"):
                if key in fm:
                    val = fm[key]
                    settings[key] = json.dumps(val) if isinstance(val, (list, dict)) else str(val)
            continue

        # Regular node
        node_id = _id_from_path(rel, vault_path.name)
        node_type = "page"  # uniform type; structure comes from folders
        # Use the actual note name for graph labels; headings are content, not identity.
        title = _title_from_stem(f.stem)

        # Visibility → roles mapping
        # Supports: string ("public", "private", "personal", "work", "friends", …)
        # or a list (["work", "friends"]) for multi-class access control.
        # "private" is an alias for "personal".
        visibility = (fm.get("visibility", DEFAULT_VISIBILITY) if fm else DEFAULT_VISIBILITY)
        if isinstance(visibility, list):
            roles = ["personal" if str(v) == "private" else str(v) for v in visibility]
        elif str(visibility) == "private":
            roles = ["personal"]
        else:
            roles = [str(visibility)]

        # Build metadata from promoted keys
        metadata: dict[str, Any] = {}
        if fm:
            for key in META_KEYS:
                if key in fm:
                    if key == "extra_meta":
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
                        val = fm[key]
                        # PyYAML parses bare dates as datetime.date — convert to ISO string
                        import datetime as _dt
                        if isinstance(val, (_dt.date, _dt.datetime)):
                            val = val.isoformat()
                        # Lists of dates (e.g. tags with date-like entries)
                        elif isinstance(val, list):
                            val = [v.isoformat() if isinstance(v, (_dt.date, _dt.datetime)) else v for v in val]
                        metadata[key] = val

        node = VaultNode(
            id=node_id,
            type=node_type,
            title=title,
            body=body.strip(),
            roles=roles,
            metadata=metadata,
            source_path=rel,
            content_hash=_content_hash(fm or {}, body),
        )
        nodes.append(node)

        # Resolve cross-link edges from wikilinks in body text
        link_edges, doc_paths = _resolve_body_wikilinks(body, node_id, filename_to_id, document_files)
        edges.extend(link_edges)
        if doc_paths:
            existing = metadata.get("extra_files", [])
            metadata["extra_files"] = list(dict.fromkeys(existing + doc_paths))

        # Add optional secondary containment parents from frontmatter.
        for parent_name in _parse_secondary_parents((fm or {}).get("secondary_parents")):
            parent_id = filename_to_id.get(parent_name)
            if not parent_id:
                log.warning("Unresolved secondary parent: [[%s]] in %s", parent_name, rel)
                continue
            if parent_id == node_id:
                continue
            edges.append(VaultEdge(
                source_id=parent_id,
                target_id=node_id,
                type="includes",
            ))

    # Detect root node: the folder note at vault root (stem matches vault folder name)
    root_note = vault_path / f"{vault_path.name}.md"
    root_id = vault_path.name if root_note.exists() else "identity"

    # Third pass: infer containment edges from folder hierarchy
    # Folder notes are the "index" of a folder; other files are children.
    for f in md_files:
        rel = str(f.relative_to(vault_path))
        if f.name in ("_system.md", "_config.md"):
            continue

        node_id = file_node_ids.get(rel)
        if not node_id:
            continue

        if _is_folder_note(f):
            # This is a folder note — its parent is:
            #   - the folder note of the grandparent directory, or
            #   - root (if at top level or IS the vault root)
            if f.parent == vault_path:
                # This IS the vault root folder note (e.g. digital-twin.md)
                # No parent edge needed
                pass
            else:
                grandparent = f.parent.parent
                if grandparent == vault_path:
                    # Top-level notebook — child of root
                    if node_id != root_id:
                        edges.append(VaultEdge(
                            source_id=root_id,
                            target_id=node_id,
                            type="includes",
                        ))
                else:
                    # Find the folder note in the grandparent directory
                    parent_note = grandparent / f"{grandparent.name}.md"
                    parent_rel = str(parent_note.relative_to(vault_path))
                    parent_id = file_node_ids.get(parent_rel)
                    if parent_id and parent_id != node_id:
                        edges.append(VaultEdge(
                            source_id=parent_id,
                            target_id=node_id,
                            type="includes",
                        ))
        else:
            # Regular file — parent is the folder note of the same directory
            parent_dir = f.parent
            if parent_dir == vault_path:
                # Top-level file — child of root
                if node_id != root_id:
                    edges.append(VaultEdge(
                        source_id=root_id,
                        target_id=node_id,
                        type="includes",
                    ))
            else:
                parent_note = parent_dir / f"{parent_dir.name}.md"
                parent_rel = str(parent_note.relative_to(vault_path))
                parent_id = file_node_ids.get(parent_rel)
                if parent_id and parent_id != node_id:
                    edges.append(VaultEdge(
                        source_id=parent_id,
                        target_id=node_id,
                        type="includes",
                    ))

    return nodes, edges, settings


# ── parent-link injector ───────────────────────────────────────────────

# Frontmatter keys managed by the sync script (written back to vault files)
MANAGED_FM_KEY = "parent"


def inject_parent_links(vault_path: Path) -> int:
    """Write a ``parent: "[[…]]"`` property into every vault note's frontmatter.

    The parent is derived from the folder hierarchy:
    * A **folder note** (e.g. ``Career/Career.md``) gets the grandparent
      folder note as parent.
    * A **regular file** (e.g. ``Career/Youwe.md``) gets the folder note
      of its directory as parent.
    * Top-level files/folders get the vault-root folder note as parent.
    * The vault-root folder note itself (``digital-twin.md``) gets no parent.

    Returns the number of files updated.
    """
    root_note = vault_path / f"{vault_path.name}.md"
    root_stem = vault_path.name if root_note.exists() else None

    md_files: list[Path] = []
    for f in sorted(vault_path.rglob("*.md")):
        rel = f.relative_to(vault_path)
        if any(part.startswith(".") for part in rel.parts):
            continue
        if rel.parts and rel.parts[0] == "templates":
            continue
        if f.name in ("_system.md", "_config.md"):
            continue
        md_files.append(f)

    updated = 0

    for f in md_files:
        # Determine desired parent stem
        parent_stem = _determine_parent_stem(f, vault_path, root_stem)

        # Read file
        content = f.read_text(encoding="utf-8")
        fm_dict, body = _parse_frontmatter(content)

        current_parent = fm_dict.get(MANAGED_FM_KEY, "")
        desired_value = f"\"[[{parent_stem}]]\"" if parent_stem else ""

        # Extract the current wikilink target from the parent value
        current_target = ""
        if current_parent:
            m = WIKILINK_RE.search(str(current_parent))
            if m:
                current_target = m.group(1).strip()

        if current_target == (parent_stem or ""):
            continue  # already correct

        # Rebuild frontmatter with updated parent
        new_content = _rebuild_with_parent(content, parent_stem)
        if new_content != content:
            f.write_text(new_content, encoding="utf-8")
            updated += 1
            log.debug("parent link: %s → [[%s]]", f.relative_to(vault_path), parent_stem)

    return updated


def _determine_parent_stem(f: Path, vault_path: Path, root_stem: str | None) -> str | None:
    """Return the stem of the parent note for file *f*, or None for the root.

    Walks up the directory tree to find the nearest ancestor with a folder note.
    """
    if root_stem and f.stem == root_stem and f.parent == vault_path:
        return None  # vault root note has no parent

    if _is_folder_note(f):
        # Folder note: parent is the nearest ancestor folder note above the parent dir
        return _find_ancestor_folder_note(f.parent.parent, vault_path, root_stem)
    else:
        # Regular file: parent is the folder note of its directory (or walk up)
        return _find_ancestor_folder_note(f.parent, vault_path, root_stem)


def _find_ancestor_folder_note(start_dir: Path, vault_path: Path, root_stem: str | None) -> str | None:
    """Walk up from *start_dir* to find the nearest directory with a folder note."""
    current = start_dir
    while current != vault_path and current.is_relative_to(vault_path):
        folder_note = current / f"{current.name}.md"
        if folder_note.exists():
            return folder_note.stem
        current = current.parent
    return root_stem


def _rebuild_with_parent(content: str, parent_stem: str | None) -> str:
    """Insert or update the ``parent`` key in YAML frontmatter."""
    m = FRONTMATTER_RE.match(content)
    if not m:
        # No frontmatter — create one
        if parent_stem:
            return f'---\nparent: "[[{parent_stem}]]"\n---\n\n{content}'
        return content

    fm_text = m.group(1)
    after_fm = content[m.end():]

    # Remove any existing parent line
    fm_lines = fm_text.split("\n")
    fm_lines = [l for l in fm_lines if not l.strip().startswith(f"{MANAGED_FM_KEY}:")]

    # Add new parent line (at end, before closing ---)
    if parent_stem:
        fm_lines.append(f'parent: "[[{parent_stem}]]"')

    new_fm = "\n".join(fm_lines)
    return f"---\n{new_fm}\n---\n{after_fm}"


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


def _compute_edge_roles(db: sqlite3.Connection, source_id: str, target_id: str) -> list[str]:
    """Derive edge roles from endpoint nodes.

    Uses the intersection of both endpoints' roles so the edge is
    visible to anyone who can see both nodes.  Falls back to the
    union when one node is missing.
    """
    src_row = db.execute("SELECT roles FROM nodes WHERE id=?", (source_id,)).fetchone()
    tgt_row = db.execute("SELECT roles FROM nodes WHERE id=?", (target_id,)).fetchone()
    src_roles = set(_safe_json(src_row["roles"], [])) if src_row else set()
    tgt_roles = set(_safe_json(tgt_row["roles"], [])) if tgt_row else set()
    if src_roles and tgt_roles:
        return sorted(src_roles & tgt_roles)
    return sorted(src_roles | tgt_roles)


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

        def _json(obj: Any) -> str:
            """JSON serialiser that converts date/datetime to ISO strings."""
            if isinstance(obj, (date, datetime)):
                return obj.isoformat()
            raise TypeError(f'Object of type {obj.__class__.__name__} is not JSON serializable')

        # Create nodes
        for n in diff.nodes_to_create:
            db.execute("""
                INSERT INTO nodes (id, type, title, body, metadata, roles, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (n.id, n.type, n.title, n.body,
                  json.dumps(n.metadata, default=_json), json.dumps(n.roles), now, now))
            counts["created"] += 1

        # Update nodes
        for n in diff.nodes_to_update:
            db.execute("""
                UPDATE nodes SET type=?, title=?, body=?, metadata=?, roles=?, updated_at=?
                WHERE id=?
            """, (n.type, n.title, n.body,
                  json.dumps(n.metadata, default=_json), json.dumps(n.roles), now, n.id))
            counts["updated"] += 1

        # Delete edges
        for eid in diff.edges_to_delete:
            db.execute("DELETE FROM edges WHERE id = ?", (eid,))
            counts["edges_deleted"] += 1

        # Create edges
        for e in diff.edges_to_create:
            eid = hashlib.sha256(f"{e.source_id}:{e.target_id}:{e.type}".encode()).hexdigest()[:16]
            try:
                edge_roles = _compute_edge_roles(db, e.source_id, e.target_id)
                db.execute("""
                    INSERT INTO edges (id, source_id, target_id, type, label, roles, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (eid, e.source_id, e.target_id, e.type, e.label,
                      json.dumps(edge_roles), now))
                counts["edges_created"] += 1
            except sqlite3.IntegrityError:
                # Edge already exists (unique constraint) — skip
                log.debug("edge already exists: %s → %s (%s)", e.source_id, e.target_id, e.type)

        # Refresh roles on ALL edges (covers pre-existing edges with stale roles)
        for row in db.execute("SELECT id, source_id, target_id FROM edges"):
            edge_roles = _compute_edge_roles(db, row["source_id"], row["target_id"])
            db.execute("UPDATE edges SET roles = ? WHERE id = ?",
                       (json.dumps(edge_roles), row["id"]))

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

    # Inject/update parent links in vault files first
    n_parent = inject_parent_links(vault_path)
    if n_parent:
        log.info("   🔗 Updated parent links in %d files", n_parent)

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
            roles TEXT DEFAULT '["personal"]',
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
