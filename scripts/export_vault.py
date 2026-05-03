#!/usr/bin/env python3
"""Export the SQLite knowledge graph to an Obsidian vault.

Usage:
    python scripts/export_vault.py [--db data/knowledge.db] [--out ~/ObsidianVault/digital-twin]

Each node becomes a .md file with YAML frontmatter.
Containment edges map to folder structure.
Cross-link edges map to frontmatter `links:` entries.
Documents with file_path get their binaries copied.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sqlite3
from pathlib import Path


# ── helpers ────────────────────────────────────────────────────────────

def _safe_json(val: str | None, default=None):
    if not val or not val.strip():
        return default
    try:
        return json.loads(val)
    except (json.JSONDecodeError, TypeError):
        return default


def _is_uuid(s: str) -> bool:
    """Check if a string looks like a UUID."""
    return bool(re.match(r'^[0-9a-f]{8}-[0-9a-f]{4}-', s))


def _slugify(node_id: str) -> str:
    """Convert node ID to a filesystem-safe filename slug."""
    return re.sub(r'[<>:"/\\|?*]', '_', node_id)


def _title_to_slug(title: str) -> str:
    """Convert a node title to a clean filename slug."""
    # Lower, replace spaces/special with hyphens, collapse multiples
    slug = title.lower()
    slug = re.sub(r'[^a-z0-9\s-]', '', slug)
    slug = re.sub(r'[\s_]+', '-', slug)
    slug = re.sub(r'-+', '-', slug)
    slug = slug.strip('-')
    return slug or 'untitled'


def _yaml_list(items: list) -> str:
    """Format a list for YAML frontmatter."""
    if not items:
        return "[]"
    if len(items) == 1:
        return f"[{items[0]}]"
    return "[" + ", ".join(str(i) for i in items) + "]"


def _yaml_value(val) -> str:
    """Format a value for YAML frontmatter."""
    if isinstance(val, bool):
        return "true" if val else "false"
    if isinstance(val, (int, float)):
        return str(val)
    if isinstance(val, str):
        # Quote strings that contain special YAML chars
        if any(c in val for c in ':{}[]#&*!|>\'"%@`'):
            return f'"{val}"'
        return val
    return str(val)


# ── data loading ───────────────────────────────────────────────────────

def load_nodes(db: sqlite3.Connection) -> dict[str, dict]:
    db.row_factory = sqlite3.Row
    nodes = {}
    for r in db.execute("SELECT * FROM nodes"):
        nodes[r["id"]] = {
            "id": r["id"],
            "type": r["type"],
            "title": r["title"],
            "body": r["body"] or "",
            "metadata": _safe_json(r["metadata"], {}),
            "roles": _safe_json(r["roles"], ["public"]),
            "created_at": r["created_at"],
            "updated_at": r["updated_at"],
        }
    return nodes


def load_edges(db: sqlite3.Connection) -> list[dict]:
    db.row_factory = sqlite3.Row
    edges = []
    for r in db.execute("SELECT * FROM edges"):
        edges.append({
            "id": r["id"],
            "source_id": r["source_id"],
            "target_id": r["target_id"],
            "type": r["type"],
            "label": r["label"],
            "roles": _safe_json(r["roles"], []),
        })
    return edges


def load_settings(db: sqlite3.Connection) -> dict[str, str]:
    db.row_factory = sqlite3.Row
    settings = {}
    for r in db.execute("SELECT key, value FROM settings"):
        settings[r["key"]] = r["value"]
    return settings


def load_translations(db: sqlite3.Connection) -> list[dict]:
    db.row_factory = sqlite3.Row
    rows = []
    for r in db.execute("SELECT key, source_en, text_nl, is_manual, stale FROM translations"):
        rows.append({
            "key": r["key"],
            "source_en": r["source_en"],
            "text_nl": r["text_nl"],
            "is_manual": bool(r["is_manual"]),
            "stale": bool(r["stale"]),
        })
    return rows


# ── tree builder ───────────────────────────────────────────────────────

CONTAINMENT_EDGE_TYPES = {"has", "includes", "nb_page"}


def build_tree(nodes: dict, edges: list) -> dict[str, str]:
    """Build a mapping of node_id → folder path from containment edges.

    Returns dict like:
        {"identity": ".", "nb-work": "work", "career": "work/career", ...}
    """
    # Build parent → children map from containment edges
    children: dict[str, list[str]] = {}
    parent_of: dict[str, str] = {}
    for e in edges:
        if e["type"] in CONTAINMENT_EDGE_TYPES:
            children.setdefault(e["source_id"], []).append(e["target_id"])
            parent_of[e["target_id"]] = e["source_id"]

    # Find root nodes (nodes that are parents but have no parent themselves)
    all_children = set(parent_of.keys())
    all_parents = set(children.keys())
    roots = all_parents - all_children
    # Also add nodes that aren't in any edge at all
    orphans = set(nodes.keys()) - all_children - all_parents

    # Map node IDs to folder-friendly names
    def folder_name(node_id: str) -> str:
        node = nodes.get(node_id)
        if not node:
            return _slugify(node_id)
        # For UUID-named nodes, use the title as the slug
        if _is_uuid(node_id) and node.get("title"):
            return _title_to_slug(node["title"])
        return _slugify(node_id)

    # BFS to assign paths
    paths: dict[str, str] = {}

    # Special handling: "identity" is the root, maps to "."
    if "identity" in nodes:
        paths["identity"] = "."
        queue = list(children.get("identity", []))
    else:
        queue = list(roots)

    # Map top-level notebook nodes to cleaner folder names
    FOLDER_OVERRIDES = {
        "nb-work": "work",
        "nb-personal": "personal",
        "education": "education",
        "hobbies": "hobbies",
    }

    # Process queue
    visited = set(paths.keys())
    # Add identity's children first
    for nid in list(queue):
        name = FOLDER_OVERRIDES.get(nid, folder_name(nid))
        paths[nid] = name
        visited.add(nid)

    # BFS
    while queue:
        nid = queue.pop(0)
        for child_id in children.get(nid, []):
            if child_id in visited:
                continue
            parent_path = paths.get(nid, ".")
            child_name = folder_name(child_id)
            paths[child_id] = f"{parent_path}/{child_name}" if parent_path != "." else child_name
            visited.add(child_id)
            queue.append(child_id)

    # Remaining roots
    for nid in roots:
        if nid not in paths:
            paths[nid] = folder_name(nid)
            visited.add(nid)
            queue.append(nid)
            while queue:
                cur = queue.pop(0)
                for child_id in children.get(cur, []):
                    if child_id in visited:
                        continue
                    parent_path = paths.get(cur, ".")
                    child_name = folder_name(child_id)
                    paths[child_id] = f"{parent_path}/{child_name}"
                    visited.add(child_id)
                    queue.append(child_id)

    # Orphans go to top level
    for nid in orphans:
        if nid not in paths:
            paths[nid] = folder_name(nid)

    return paths


# ── cross-link builder ─────────────────────────────────────────────────

def build_crosslinks(nodes: dict, edges: list) -> dict[str, dict[str, list[str]]]:
    """Build a mapping of node_id → {edge_type: [target_ids]}.

    Only includes non-containment edges.
    """
    links: dict[str, dict[str, list[str]]] = {}
    for e in edges:
        if e["type"] not in CONTAINMENT_EDGE_TYPES:
            links.setdefault(e["source_id"], {}).setdefault(e["type"], []).append(e["target_id"])
    return links


def build_extra_containment(nodes: dict, edges: list, node_paths: dict) -> dict[str, dict[str, list[str]]]:
    """Find containment edges that CANNOT be inferred from the folder structure.

    A folder tree can only express single-parent. Some nodes in the original DB
    have multiple parents (e.g. experience--earlier is under both education AND
    career). The primary parent is the folder parent; additional parents need
    explicit frontmatter entries.

    Also captures the edge type (has vs includes) when it differs from the
    default 'includes' that the folder hierarchy implies.
    """
    extra: dict[str, dict[str, list[str]]] = {}  # source_id → {edge_type: [target_ids]}

    # Build the folder-inferred parent map
    folder_parent: dict[str, str] = {}  # child_id → parent_id (from folder structure)
    for node_id, path in node_paths.items():
        if path == ".":
            continue  # root
        parts = path.split("/")
        if len(parts) >= 2:
            # Find the parent node ID from the parent path
            parent_path = "/".join(parts[:-1])
            for pid, pp in node_paths.items():
                if pp == parent_path:
                    folder_parent[node_id] = pid
                    break
        else:
            # Top-level → parent is identity (root)
            folder_parent[node_id] = "identity"

    for e in edges:
        if e["type"] not in CONTAINMENT_EDGE_TYPES:
            continue
        source = e["source_id"]
        target = e["target_id"]
        etype = e["type"]

        # Check if this edge is already expressed by the folder hierarchy
        if folder_parent.get(target) == source:
            # The folder hierarchy will generate an 'includes' edge for this.
            # Don't emit anything extra — normalize has→includes for simplicity.
            continue

        # This is a multi-parent edge not expressible by folder structure
        extra.setdefault(source, {}).setdefault(etype, []).append(target)

    return extra


def _wikilink_name(node_id: str, nodes: dict) -> str:
    """Get the wikilink-friendly name for a node."""
    node = nodes.get(node_id)
    if node and _is_uuid(node_id) and node.get("title"):
        return _title_to_slug(node["title"])
    return _slugify(node_id)


# ── frontmatter builder ───────────────────────────────────────────────

# Metadata keys that get promoted to top-level frontmatter fields
PROMOTED_META_KEYS = {"featured", "icon", "order", "notebook_root", "url"}
# Metadata keys to skip entirely (internal/block editor artifacts)
SKIP_META_KEYS = {"body_blocks", "source_file"}


def build_frontmatter(node: dict, crosslinks: dict[str, list[str]],
                      node_paths: dict[str, str], nodes: dict,
                      extra_containment: dict[str, list[str]] | None = None) -> str:
    """Build YAML frontmatter string for a node."""
    lines = ["---"]

    # Type (always first)
    lines.append(f"type: {node['type']}")

    # Original DB ID (needed for sync pipeline to map back)
    lines.append(f"id: {node['id']}")

    # Title
    lines.append(f"title: \"{node['title']}\"")

    # Roles
    roles = node.get("roles", ["public"])
    if not roles:
        roles = ["public"]
    lines.append(f"roles: {_yaml_list(roles)}")

    # Promoted metadata fields
    meta = node.get("metadata", {})
    for key in sorted(PROMOTED_META_KEYS):
        if key in meta:
            lines.append(f"{key}: {_yaml_value(meta[key])}")

    # Document file_path → file reference
    if "file_path" in meta:
        lines.append(f"file: \"{meta['file_path']}\"")
        if "original_filename" in meta:
            lines.append(f"original_filename: \"{meta['original_filename']}\"")
        if "mime_type" in meta:
            lines.append(f"mime_type: {meta['mime_type']}")

    # Extra files (publications node)
    if "extra_files" in meta:
        lines.append("extra_files:")
        for ef in meta["extra_files"]:
            lines.append(f"  - file: \"{ef.get('file_path', '')}\"")
            if "original_filename" in ef:
                lines.append(f"    original_filename: \"{ef['original_filename']}\"")

    # URL
    if "url" in meta:
        pass  # already handled in promoted keys

    # Cross-link edges as wikilinks
    all_links = dict(crosslinks) if crosslinks else {}
    # Merge extra containment edges (multi-parent or has-type)
    if extra_containment:
        for etype, targets in extra_containment.items():
            if etype in all_links:
                all_links[etype].extend(targets)
            else:
                all_links[etype] = list(targets)

    if all_links:
        lines.append("links:")
        for edge_type, targets in sorted(all_links.items()):
            wikilinks = []
            for t in targets:
                # Use the slugified name for the wikilink
                wl_name = _wikilink_name(t, nodes)
                wikilinks.append(f"\"[[{wl_name}]]\"")
            if len(wikilinks) == 1:
                lines.append(f"  {edge_type}: {wikilinks[0]}")
            else:
                lines.append(f"  {edge_type}: [{', '.join(wikilinks)}]")

    # Remaining non-promoted, non-skipped metadata
    remaining = {k: v for k, v in meta.items()
                 if k not in PROMOTED_META_KEYS
                 and k not in SKIP_META_KEYS
                 and k not in ("file_path", "original_filename", "mime_type",
                               "extra_files", "size_bytes")}
    if remaining:
        lines.append(f"extra_meta: {json.dumps(remaining)}")

    lines.append("---")
    return "\n".join(lines)


# ── file writer ────────────────────────────────────────────────────────

def write_vault(nodes: dict, edges: list, settings: dict,
                translations: list, db_path: Path, out_dir: Path):
    """Write the full Obsidian vault to out_dir."""
    out_dir.mkdir(parents=True, exist_ok=True)

    # Build tree and crosslinks
    node_paths = build_tree(nodes, edges)
    crosslinks = build_crosslinks(nodes, edges)
    extra_containment = build_extra_containment(nodes, edges, node_paths)

    written = 0
    skipped = 0

    for node_id, node in nodes.items():
        # Skip system node — handled separately
        if node["type"] == "system":
            continue

        # Determine output path
        base_path = node_paths.get(node_id)
        if base_path is None:
            print(f"  WARN: no path for node {node_id}, placing at root")
            base_path = _slugify(node_id)

        # If the node has children, it becomes folder/node_id.md (index file)
        has_children = any(
            e["type"] in CONTAINMENT_EDGE_TYPES and e["source_id"] == node_id
            for e in edges
        )

        if has_children:
            file_path = out_dir / base_path / f"_index.md"
        else:
            # Leaf node
            parent = "/".join(base_path.split("/")[:-1]) if "/" in base_path else "."
            filename = base_path.split("/")[-1]
            if parent == ".":
                file_path = out_dir / f"{filename}.md"
            else:
                file_path = out_dir / parent / f"{filename}.md"

        # Build frontmatter
        node_crosslinks = crosslinks.get(node_id, {})
        node_extra = extra_containment.get(node_id, {})
        fm = build_frontmatter(node, node_crosslinks, node_paths, nodes, node_extra)

        # Write file
        file_path.parent.mkdir(parents=True, exist_ok=True)
        content = fm + "\n\n" + node["body"].strip() + "\n"
        file_path.write_text(content, encoding="utf-8")
        written += 1

    # Write _system.md
    system_node = nodes.get("_system")
    if system_node:
        (out_dir / "_system.md").write_text(system_node["body"].strip() + "\n", encoding="utf-8")
        written += 1

    # Write _config.md (settings)
    config_lines = ["---"]
    if "welcome_message" in settings:
        config_lines.append(f'welcome_message: "{settings["welcome_message"]}"')
    if "suggestion_chips" in settings:
        config_lines.append(f"suggestion_chips: {settings['suggestion_chips']}")
    if "translation_prompt" in settings:
        # Multi-line value
        config_lines.append("translation_prompt: |")
        for line in settings["translation_prompt"].split("\n"):
            config_lines.append(f"  {line}")
    config_lines.append("---")
    config_lines.append("")
    config_lines.append("# Website Configuration")
    config_lines.append("")
    config_lines.append("This file controls website runtime settings. Edit the frontmatter above.")
    config_lines.append("")
    (out_dir / "_config.md").write_text("\n".join(config_lines) + "\n", encoding="utf-8")
    written += 1

    # Copy document files
    docs_src = db_path.parent / "documents"
    docs_dst = out_dir / "documents"
    doc_count = 0
    if docs_src.exists():
        docs_dst.mkdir(parents=True, exist_ok=True)
        for f in docs_src.iterdir():
            if f.is_file():
                shutil.copy2(f, docs_dst / f.name)
                doc_count += 1

    # Write .obsidian/app.json for basic vault config
    obsidian_dir = out_dir / ".obsidian"
    obsidian_dir.mkdir(exist_ok=True)
    (obsidian_dir / "app.json").write_text(json.dumps({
        "showFrontmatter": True,
        "readableLineLength": True,
    }, indent=2) + "\n", encoding="utf-8")

    print(f"\n✅ Export complete:")
    print(f"   {written} markdown files written")
    print(f"   {doc_count} document files copied")
    print(f"   Vault: {out_dir}")


# ── validation ─────────────────────────────────────────────────────────

def validate_vault(nodes: dict, edges: list, out_dir: Path):
    """Quick validation: count files, check all nodes have a file."""
    md_files = list(out_dir.rglob("*.md"))
    # Exclude .obsidian
    md_files = [f for f in md_files if ".obsidian" not in str(f)]

    node_count = len(nodes)
    file_count = len(md_files)

    # Expected: one .md per non-system node + _system.md + _config.md
    non_system = sum(1 for n in nodes.values() if n["type"] != "system")
    expected = non_system + 2  # +_system.md +_config.md

    print(f"\n🔍 Validation:")
    print(f"   DB nodes: {node_count} ({non_system} non-system)")
    print(f"   MD files: {file_count}")
    print(f"   Expected: {expected}")
    if file_count == expected:
        print(f"   ✅ PASS — counts match")
    else:
        print(f"   ⚠️  MISMATCH — {file_count} files vs {expected} expected")

    # Check for nodes without files
    all_node_ids = {nid for nid, n in nodes.items() if n["type"] != "system"}
    # Scan files for node references
    file_stems = set()
    for f in md_files:
        if f.name == "_system.md" or f.name == "_config.md":
            continue
        # Read frontmatter to find type
        file_stems.add(f.stem if f.stem != "_index" else f.parent.name)

    return file_count == expected


# ── main ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Export knowledge DB to Obsidian vault")
    parser.add_argument("--db", default="data/knowledge.db", help="Path to knowledge.db")
    parser.add_argument("--out", default=str(Path.home() / "ObsidianVault" / "digital-twin"),
                        help="Output vault directory")
    args = parser.parse_args()

    db_path = Path(args.db)
    out_dir = Path(args.out)

    if not db_path.exists():
        print(f"❌ Database not found: {db_path}")
        return 1

    print(f"📖 Reading database: {db_path}")
    db = sqlite3.connect(str(db_path))

    nodes = load_nodes(db)
    edges = load_edges(db)
    settings = load_settings(db)
    translations = load_translations(db)
    db.close()

    print(f"   {len(nodes)} nodes, {len(edges)} edges, {len(settings)} settings, {len(translations)} translations")

    print(f"\n📝 Writing vault to: {out_dir}")
    write_vault(nodes, edges, settings, translations, db_path, out_dir)

    validate_vault(nodes, edges, out_dir)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
