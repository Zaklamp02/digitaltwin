"""SQLite-backed knowledge graph.

Nodes hold all memory content (replaces markdown files as source of truth).
Edges represent typed relationships between nodes.
Both nodes and edges carry RBAC roles so the graph can be filtered per caller.

Schema
------
nodes:
    id          TEXT PRIMARY KEY  (uuid4 or human slug from migration)
    type        TEXT              person|job|project|skill|education|
                                  community|document|opinion|personal|faq|system
    title       TEXT
    body        TEXT              markdown content
    metadata    TEXT              JSON object (arbitrary extra fields)
    roles       TEXT              JSON array  e.g. ["public", "recruiter"]
    created_at  TEXT              ISO-8601
    updated_at  TEXT              ISO-8601

edges:
    id          TEXT PRIMARY KEY
    source_id   TEXT FK nodes.id  ON DELETE CASCADE
    target_id   TEXT FK nodes.id  ON DELETE CASCADE
    type        TEXT              worked_at|built|knows|studied_at|member_of|
                                  relates_to|used_in|describes|authored
    label       TEXT              human-readable edge label
    roles       TEXT              JSON array
    created_at  TEXT              ISO-8601
    UNIQUE(source_id, target_id, type)
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path


def _safe_json_loads(value, default):
    """Parse JSON, falling back to default on empty or invalid input."""
    if not value or not value.strip():
        return default
    try:
        return json.loads(value)
    except (json.JSONDecodeError, ValueError):
        return default
from typing import Any

log = logging.getLogger("ask-my-agent.knowledge")

# ── constants ─────────────────────────────────────────────────────────────────

NODE_TYPES: list[str] = [
    "person", "job", "project", "skill", "education",
    "community", "document", "opinion", "personal", "faq", "system",
    "notebook",
]

EDGE_TYPES: list[str] = [
    "worked_at", "built", "knows", "studied_at", "member_of",
    "relates_to", "used_in", "describes", "authored",
    "has", "includes", "uses",
    "nb_page",   # notebook → node: this node is a page in the notebook
]

CONTAINMENT_EDGE_TYPES: set[str] = {"has", "includes", "nb_page", "member_of", "studied_at"}
CROSS_LINK_EDGE_TYPES: set[str] = {
    "relates_to", "built", "authored", "describes", "uses",
    "worked_at", "knows", "used_in",
}


def is_containment(edge_type: str) -> bool:
    """Return True if edge_type represents a containment (tree) relationship."""
    return edge_type in CONTAINMENT_EDGE_TYPES

_MIGRATION_TYPE_MAP: dict[str, str] = {
    "_system": "system",
    "career": "person",
    "identity": "person",
    "personality": "person",
    "education": "education",
    "community": "community",
    "faq": "faq",
    "opinions": "opinion",
    "stack": "opinion",
    "hobbies": "personal",
}


# ── helpers ───────────────────────────────────────────────────────────────────


def _infer_node_type(rel_path: str) -> str:
    """Infer node type from a memory-file relative path."""
    parts = rel_path.replace("\\", "/").split("/")
    stem = parts[-1].removesuffix(".md")
    if parts[0] == "experience":
        return "job"
    if parts[0] == "projects":
        return "project"
    if parts[0] == "personal":
        return "personal"
    return _MIGRATION_TYPE_MAP.get(stem, "document")


def _title_from_body(body: str, rel_path: str) -> str:
    """Extract a title from the first H1/H2 in the markdown body, or derive from path."""
    m = re.search(r"^#{1,2}\s+(.+)$", body, re.MULTILINE)
    if m:
        return m.group(1).strip()
    stem = rel_path.replace("\\", "/").split("/")[-1].removesuffix(".md")
    return stem.replace("-", " ").replace("_", " ").title()


# ── dataclasses ───────────────────────────────────────────────────────────────


@dataclass
class KnowledgeNode:
    id: str
    type: str
    title: str
    body: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    roles: list[str] = field(default_factory=lambda: ["public"])
    created_at: str = ""
    updated_at: str = ""


@dataclass
class KnowledgeEdge:
    id: str
    source_id: str
    target_id: str
    type: str
    label: str = ""
    roles: list[str] = field(default_factory=lambda: ["public"])
    created_at: str = ""


# ── KnowledgeDB ───────────────────────────────────────────────────────────────


class KnowledgeDB:
    """Thread-safe SQLite knowledge graph."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.execute("PRAGMA journal_mode = WAL")
        self._setup()

    # ── schema ────────────────────────────────────────────────────────────────

    def _setup(self) -> None:
        with self._lock, self._conn:
            self._conn.executescript("""
                CREATE TABLE IF NOT EXISTS nodes (
                    id          TEXT PRIMARY KEY,
                    type        TEXT NOT NULL DEFAULT 'document',
                    title       TEXT NOT NULL,
                    body        TEXT DEFAULT '',
                    metadata    TEXT DEFAULT '{}',
                    roles       TEXT DEFAULT '["public"]',
                    created_at  TEXT NOT NULL,
                    updated_at  TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS edges (
                    id          TEXT PRIMARY KEY,
                    source_id   TEXT NOT NULL,
                    target_id   TEXT NOT NULL,
                    type        TEXT NOT NULL,
                    label       TEXT DEFAULT '',
                    roles       TEXT DEFAULT '["public"]',
                    created_at  TEXT NOT NULL,
                    FOREIGN KEY (source_id) REFERENCES nodes(id) ON DELETE CASCADE,
                    FOREIGN KEY (target_id) REFERENCES nodes(id) ON DELETE CASCADE,
                    UNIQUE(source_id, target_id, type)
                );
                CREATE TABLE IF NOT EXISTS settings (
                    key         TEXT PRIMARY KEY,
                    value       TEXT NOT NULL,
                    updated_at  TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS deleted_seed_edges (
                    id  TEXT PRIMARY KEY
                );
                CREATE INDEX IF NOT EXISTS idx_edges_source ON edges(source_id);
                CREATE INDEX IF NOT EXISTS idx_edges_target ON edges(target_id);
                CREATE INDEX IF NOT EXISTS idx_nodes_type   ON nodes(type);
            """)

    # ── serialisation ─────────────────────────────────────────────────────────

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _row_to_node(row: sqlite3.Row) -> KnowledgeNode:
        return KnowledgeNode(
            id=row["id"],
            type=row["type"],
            title=row["title"],
            body=row["body"] or "",
            metadata=_safe_json_loads(row["metadata"], {}),
            roles=_safe_json_loads(row["roles"], ["public"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _row_to_edge(row: sqlite3.Row) -> KnowledgeEdge:
        return KnowledgeEdge(
            id=row["id"],
            source_id=row["source_id"],
            target_id=row["target_id"],
            type=row["type"],
            label=row["label"] or "",
            roles=json.loads(row["roles"] or '["public"]'),
            created_at=row["created_at"],
        )

    # ── health ────────────────────────────────────────────────────────────────

    @property
    def is_empty(self) -> bool:
        with self._lock:
            cur = self._conn.execute("SELECT COUNT(*) FROM nodes")
            return cur.fetchone()[0] == 0

    def node_count(self) -> int:
        with self._lock:
            return self._conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]

    def edge_count(self) -> int:
        with self._lock:
            return self._conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0]

    # ── node CRUD ─────────────────────────────────────────────────────────────

    def create_node(
        self,
        type: str,
        title: str,
        body: str = "",
        metadata: dict[str, Any] | None = None,
        roles: list[str] | None = None,
        id: str | None = None,
    ) -> KnowledgeNode:
        now = self._now()
        node = KnowledgeNode(
            id=id or str(uuid.uuid4()),
            type=type,
            title=title,
            body=body,
            metadata=metadata or {},
            roles=roles or ["public"],
            created_at=now,
            updated_at=now,
        )
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO nodes (id, type, title, body, metadata, roles, created_at, updated_at) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (
                    node.id, node.type, node.title, node.body,
                    json.dumps(node.metadata), json.dumps(node.roles),
                    node.created_at, node.updated_at,
                ),
            )
        return node

    def get_node(self, id: str) -> KnowledgeNode | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM nodes WHERE id = ?", (id,)).fetchone()
        return self._row_to_node(row) if row else None

    def update_node(self, id: str, **kwargs: Any) -> KnowledgeNode | None:
        allowed = {"type", "title", "body", "metadata", "roles"}
        updates = {k: v for k, v in kwargs.items() if k in allowed}
        if not updates:
            return self.get_node(id)
        # Shallow-merge incoming metadata with existing so callers can update
        # individual keys (e.g. order) without clobbering the rest.
        if "metadata" in updates:
            existing = self.get_node(id)
            if existing:
                updates["metadata"] = {**existing.metadata, **updates["metadata"]}
        for key in ("metadata", "roles"):
            if key in updates:
                updates[key] = json.dumps(updates[key])
        updates["updated_at"] = self._now()
        cols = ", ".join(f"{k} = ?" for k in updates)
        vals = list(updates.values()) + [id]
        with self._lock, self._conn:
            self._conn.execute(f"UPDATE nodes SET {cols} WHERE id = ?", vals)  # noqa: S608
        return self.get_node(id)

    def delete_node(self, id: str) -> bool:
        with self._lock, self._conn:
            cur = self._conn.execute("DELETE FROM nodes WHERE id = ?", (id,))
        return cur.rowcount > 0

    def list_nodes(
        self,
        type_filter: str | None = None,
        role_filter: list[str] | None = None,
    ) -> list[KnowledgeNode]:
        with self._lock:
            if type_filter:
                rows = self._conn.execute(
                    "SELECT * FROM nodes WHERE type = ? ORDER BY type, title", (type_filter,)
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT * FROM nodes ORDER BY type, title"
                ).fetchall()
        nodes = [self._row_to_node(r) for r in rows]
        if role_filter:
            role_set = set(role_filter)
            nodes = [n for n in nodes if role_set.intersection(set(n.roles))]
        return nodes

    def search_nodes(self, query: str) -> list[KnowledgeNode]:
        q = f"%{query}%"
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM nodes WHERE title LIKE ? OR body LIKE ? ORDER BY type, title",
                (q, q),
            ).fetchall()
        return [self._row_to_node(r) for r in rows]

    # ── edge CRUD ─────────────────────────────────────────────────────────────

    def create_edge(
        self,
        source_id: str,
        target_id: str,
        type: str,
        label: str = "",
        roles: list[str] | None = None,
    ) -> KnowledgeEdge:
        now = self._now()
        edge = KnowledgeEdge(
            id=str(uuid.uuid4()),
            source_id=source_id,
            target_id=target_id,
            type=type,
            label=label,
            roles=roles or ["public"],
            created_at=now,
        )
        with self._lock, self._conn:
            try:
                self._conn.execute(
                    "INSERT INTO edges (id, source_id, target_id, type, label, roles, created_at) "
                    "VALUES (?,?,?,?,?,?,?)",
                    (
                        edge.id, edge.source_id, edge.target_id,
                        edge.type, edge.label, json.dumps(edge.roles), edge.created_at,
                    ),
                )
            except sqlite3.IntegrityError:
                # Edge already exists — return the existing one
                row = self._conn.execute(
                    "SELECT * FROM edges WHERE source_id=? AND target_id=? AND type=?",
                    (source_id, target_id, type),
                ).fetchone()
                if row:
                    return self._row_to_edge(row)
        return edge

    def get_edge(self, id: str) -> KnowledgeEdge | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM edges WHERE id = ?", (id,)).fetchone()
        return self._row_to_edge(row) if row else None

    def get_edges_for_node(self, node_id: str) -> list[KnowledgeEdge]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM edges WHERE source_id = ? OR target_id = ?",
                (node_id, node_id),
            ).fetchall()
        return [self._row_to_edge(r) for r in rows]

    def list_edges(self, node_id: str | None = None) -> list[KnowledgeEdge]:
        with self._lock:
            if node_id:
                rows = self._conn.execute(
                    "SELECT * FROM edges WHERE source_id = ? OR target_id = ?",
                    (node_id, node_id),
                ).fetchall()
            else:
                rows = self._conn.execute("SELECT * FROM edges").fetchall()
        return [self._row_to_edge(r) for r in rows]

    def delete_edge(self, id: str) -> bool:
        with self._lock, self._conn:
            cur = self._conn.execute("DELETE FROM edges WHERE id = ?", (id,))
            if cur.rowcount > 0 and id in _ALL_SEEDED_IDS:
                self._conn.execute(
                    "INSERT OR IGNORE INTO deleted_seed_edges (id) VALUES (?)", (id,)
                )
        return cur.rowcount > 0

    # ── graph export ──────────────────────────────────────────────────────────

    def get_graph(self, caller_roles: list[str] | None = None) -> dict[str, Any]:
        """Return graph data suitable for frontend visualization."""
        from collections import deque

        role_set = set(caller_roles) if caller_roles else None
        nodes = self.list_nodes()
        edges = self.list_edges()
        if role_set:
            nodes = [n for n in nodes if role_set.intersection(set(n.roles))]
            node_ids_set = {n.id for n in nodes}
            edges = [
                e for e in edges
                if role_set.intersection(set(e.roles))
                and e.source_id in node_ids_set
                and e.target_id in node_ids_set
            ]

        # BFS tiers from identity root (tier 0 = root, tier N = N hops away)
        all_node_ids = {n.id for n in nodes}
        root = next((n.id for n in nodes if n.id == "identity"), None)
        if root is None:
            root = next((n.id for n in nodes if n.type == "person"), None)
        tiers: dict[str, int] = {}
        if root and root in all_node_ids:
            queue: deque[tuple[str, int]] = deque([(root, 0)])
            visited: set[str] = {root}
            while queue:
                nid, depth = queue.popleft()
                tiers[nid] = depth
                for e in edges:
                    nbr: str | None = None
                    if e.source_id == nid and e.target_id not in visited and e.target_id in all_node_ids:
                        nbr = e.target_id
                    elif e.target_id == nid and e.source_id not in visited and e.source_id in all_node_ids:
                        nbr = e.source_id
                    if nbr:
                        visited.add(nbr)
                        queue.append((nbr, depth + 1))
        max_tier = max(tiers.values(), default=2)

        return {
            "nodes": [
                {
                    "id": n.id,
                    "type": n.type,
                    "title": n.title,
                    "roles": n.roles,
                    "edge_count": sum(
                        1 for e in edges
                        if e.source_id == n.id or e.target_id == n.id
                    ),
                    "tier": tiers.get(n.id, max_tier + 1),
                    "has_document": bool(n.metadata.get("file_path") or n.metadata.get("extra_files")),
                    "featured": bool(n.metadata.get("featured")),
                }
                for n in nodes
            ],
            "edges": [
                {
                    "id": e.id,
                    "source": e.source_id,
                    "target": e.target_id,
                    "type": e.type,
                    "label": e.label,
                }
                for e in edges
            ],
        }

    # ── system prompt ─────────────────────────────────────────────────────────

    def get_system_prompt(self) -> str | None:
        """Return the body of the system node, or None if not found."""
        with self._lock:
            row = self._conn.execute(
                "SELECT body FROM nodes WHERE type = 'system' ORDER BY updated_at DESC LIMIT 1"
            ).fetchone()
        return row["body"] if row else None

    def get_setting(self, key: str, default: str | None = None) -> str | None:
        """Return a value from the settings table."""
        with self._lock:
            row = self._conn.execute(
                "SELECT value FROM settings WHERE key = ?", (key,)
            ).fetchone()
        return row["value"] if row else default

    def set_setting(self, key: str, value: str) -> None:
        """Upsert a value in the settings table."""
        now = self._now()
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO settings (key, value, updated_at) VALUES (?, ?, ?)"
                " ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
                (key, value, now),
            )

    # ── lifecycle ─────────────────────────────────────────────────────────────

    def close(self) -> None:
        self._conn.close()


# ── migration ─────────────────────────────────────────────────────────────────


def migrate_from_memory(memory_dir: Path, db: KnowledgeDB) -> int:
    """Read all .md files from memory_dir and insert them as knowledge nodes.

    Should only be called once when the DB is empty.  The original files are
    left in place so they continue to pass their existing tests.
    """
    import yaml

    _YAML_FM = re.compile(r"^---\s*\n(.*?)\n---\s*\n?", re.DOTALL)
    _HTML_TIER = re.compile(r"<!--\s*tier:\s*(\w+)\s*-->")
    _TIER_TO_ROLES = {
        "public": ["public"],
        "recruiter": ["public", "work"],  # legacy alias
        "personal": ["personal"],
        "system": ["personal"],
    }

    def _parse_roles_from_md(text: str) -> list[str]:
        """Extract roles from YAML frontmatter or legacy HTML-comment tiers."""
        m = _YAML_FM.match(text)
        if m:
            try:
                fm = yaml.safe_load(m.group(1)) or {}
                if "roles" in fm:
                    return list(fm["roles"])
                if "tier" in fm:
                    return _TIER_TO_ROLES.get(fm["tier"], ["public"])
            except Exception:
                pass
        m2 = _HTML_TIER.search(text)
        if m2:
            return _TIER_TO_ROLES.get(m2.group(1), ["public"])
        return ["public"]

    def _strip_frontmatter(text: str) -> str:
        """Remove YAML frontmatter and leading HTML-comment tier lines."""
        text = _YAML_FM.sub("", text, count=1)
        text = re.sub(r"<!--.*?-->\n?", "", text)
        return text.strip()

    migrated = 0
    if not memory_dir.exists():
        log.info("memory_dir %s does not exist — skipping markdown sync", memory_dir)
        return 0
    for path in sorted(memory_dir.rglob("*.md")):
        try:
            rel = str(path.relative_to(memory_dir))
            # System prompt → system node in the DB
            if rel == "_system.md":
                node_type = "system"
                node_id = "_system"
            else:
                node_type = _infer_node_type(rel)
                node_id = rel.removesuffix(".md").replace("/", "--")
            raw = path.read_text(encoding="utf-8")
            roles = _parse_roles_from_md(raw)
            body = _strip_frontmatter(raw)
            title = _title_from_body(body, rel)
            # Upsert: insert new nodes, and update body/title/roles on every startup so
            # edits to .md files are reflected after a redeploy/restart.
            now = datetime.now(timezone.utc).isoformat()
            with db._lock, db._conn:
                db._conn.execute(
                    "INSERT INTO nodes "
                    "(id, type, title, body, metadata, roles, created_at, updated_at) "
                    "VALUES (?,?,?,?,?,?,?,?) "
                    "ON CONFLICT(id) DO UPDATE SET "
                    "  title      = excluded.title, "
                    "  body       = excluded.body, "
                    "  roles      = excluded.roles, "
                    "  updated_at = excluded.updated_at "
                    "WHERE nodes.body IS NOT excluded.body "
                    "   OR nodes.title IS NOT excluded.title "
                    "   OR nodes.roles IS NOT excluded.roles",
                    (
                        node_id, node_type, title, body,
                        json.dumps({"source_file": rel}), json.dumps(roles),
                        now, now,
                    ),
                )
                changed = db._conn.execute("SELECT changes()").fetchone()[0]
            if changed:
                migrated += 1
                log.info("synced %s → node %s (%s, roles=%s)", rel, node_id, node_type, roles)
        except Exception:
            log.exception("failed to migrate %s", path)
    log.info("memory sync complete: %d node(s) created or updated", migrated)
    return migrated


# ── canonical seed edges ──────────────────────────────────────────────────────
#
# Four-notebook pillar structure:
#   identity → nb-work / education / nb-personal / hobbies
# Each notebook root has containment children (chapters/pages).
# Cross-links connect nodes across the tree.
#
# _ALL_SEEDED_IDS includes historical IDs so a resync removes old edges cleanly.

_ALL_SEEDED_IDS: frozenset[str] = frozenset({
    # ── historical tier-1 (identity → hub) — now removed ─────────────────────
    "id--career", "id--education", "id--community", "id--personality",
    "id--personal", "id--hobbies", "id--faq",
    "id--family", "id--certifications", "id--engagements", "id--publication",
    # ── notebook pillars (identity → notebook roots) ──────────────────────────
    "id--nb-work", "id--nb-education", "id--nb-personal", "id--nb-hobbies",
    # ── notebook → chapter containment ────────────────────────────────────────
    "nb-work--career", "nb-work--community", "nb-work--publication",
    "nb-work--stack", "nb-work--faq", "nb-work--cv", "nb-work--images",
    "nb-personal--personality", "nb-personal--personal-context",
    "nb-personal--family",
    # ── chapter → page containment ────────────────────────────────────────────
    "career--youwe", "career--fiod", "career--philips", "career--earlier",
    "career--stack",
    "personality--opinions",
    "personality--faq", "personality--anecdotes", "personality--disc-incl",
    "personality--pldj-incl", "personality--opinions-incl",
    "youwe--pricing", "youwe--travel", "youwe--prodplat",
    "youwe--pricing-incl", "youwe--travel-incl", "youwe--prodplat-incl",
    "hobbies--dromenbrouwer", "hobbies--houtenjong",
    "youwe--clients",
    "clients--pricing", "clients--travel", "clients--prodplat",
    "education--certifications", "education--training",
    "certifications--iso-cert",
    "family--family-personal",
    "community--engagements",
    "earlier--publication", "identity--publication", "philips--publication",
    "personal--anecdotes-link", "personal--childhood-link",
    "personal--philips-years-link",
    # ── cross-links ───────────────────────────────────────────────────────────
    "cv--identity", "images--identity", "faq--identity",
    "philips-personal--philips-exp", "childhood--education",
    "dromenbrouwer--personal",
    "personality--disc", "personality--pldj",
    # ── legacy edges (removed in resync) ──────────────────────────────────────
    "id--youwe", "id--fiod", "id--philips", "id--earlier",
    "id--opinions",
    "anecdotes--identity", "context--identity",
    "stack--youwe", "stack--philips",
    "cv--career", "cv--education",
    "youwe--houtenjong", "earlier--dromenbrouwer",
})

_SEED_EDGES: list[tuple[str, str, str, str, str]] = [
    # (source_id, target_id, edge_type, label, edge_id)

    # ── Identity → four notebook pillars ─────────────────────────────────────
    ("identity", "nb-work",          "has",        "Work",                 "id--nb-work"),
    ("identity", "education",        "has",        "Education",            "id--nb-education"),
    ("identity", "nb-personal",      "has",        "Personal",             "id--nb-personal"),
    ("identity", "hobbies",          "has",        "Hobbies",              "id--nb-hobbies"),

    # ── Work notebook → chapters ──────────────────────────────────────────────
    ("nb-work",  "career",            "includes", "Career",               "nb-work--career"),
    ("nb-work",  "community",         "includes", "Community",            "nb-work--community"),
    ("nb-work",  "publication",       "includes", "Publications",         "nb-work--publication"),
    ("nb-work",  "stack",             "includes", "Tech Stack",           "nb-work--stack"),
    ("nb-work",  "faq",               "includes", "FAQ",                  "nb-work--faq"),
    ("nb-work",  "cv",                "includes", "CV",                   "nb-work--cv"),


    # ── Personal notebook → chapters ─────────────────────────────────────────
    ("nb-personal", "personality",       "includes", "Personality",       "nb-personal--personality"),
    ("nb-personal", "personal--context", "includes", "Personal Life",    "nb-personal--personal-context"),
    ("nb-personal", "family",            "includes", "Family",           "nb-personal--family"),

    # ── Career hub → experiences + tech stack ─────────────────────────────────
    ("career", "experience--youwe",   "includes", "Director DS&AI at Youwe",         "career--youwe"),
    ("career", "experience--fiod",    "includes", "Manager Digital Forensics, FIOD", "career--fiod"),
    ("career", "experience--philips", "includes", "Scientist at Philips",            "career--philips"),
    ("career", "experience--earlier", "includes", "Earlier career",                  "career--earlier"),
    ("career", "stack",               "uses",     "Technology stack",                "career--stack"),

    # ── Personality hub → children ────────────────────────────────────────────
    ("personality", "opinions", "relates_to", "Opinions & views", "personality--opinions"),
    ("personality", "opinions", "includes",   "Opinions",          "personality--opinions-incl"),
    ("personality", "faq",     "includes",    "FAQ",               "personality--faq"),
    ("personality", "personal--anecdotes", "includes", "Anecdotes", "personality--anecdotes"),
    ("personality", "disc",    "includes",    "DISC profile",      "personality--disc-incl"),
    ("personality", "pldj",    "includes",    "PLDJ",              "personality--pldj-incl"),

    # ── Experiences → projects (containment via includes) ─────────────────────
    ("experience--youwe",   "projects--pricing-engine",   "built",    "Pricing engine",   "youwe--pricing"),
    ("experience--youwe",   "projects--travel-bot",       "built",    "Travel bot",       "youwe--travel"),
    ("experience--youwe",   "projects--product-platform", "built",    "Product platform", "youwe--prodplat"),
    ("experience--youwe",   "projects--pricing-engine",   "includes", "Pricing Engine",   "youwe--pricing-incl"),
    ("experience--youwe",   "projects--travel-bot",       "includes", "Travel Bot",       "youwe--travel-incl"),
    ("experience--youwe",   "projects--product-platform", "includes", "Product Platform", "youwe--prodplat-incl"),

    # ── Hobbies → personal projects ───────────────────────────────────────────
    ("hobbies",             "projects--dromenbrouwer",    "includes", "DromenBrouwer", "hobbies--dromenbrouwer"),
    ("hobbies",             "projects--houtenjong",       "includes", "HoutenJong",    "hobbies--houtenjong"),

    # ── Youwe → Clients ───────────────────────────────────────────────────────
    ("experience--youwe",   "clients",                    "has",       "Client projects",       "youwe--clients"),
    ("clients",             "projects--pricing-engine",   "relates_to", "Pricing Engine",       "clients--pricing"),
    ("clients",             "projects--travel-bot",       "relates_to", "Travel Bot",            "clients--travel"),
    ("clients",             "projects--product-platform", "relates_to", "Product Platform",      "clients--prodplat"),

    # ── Education hierarchy ────────────────────────────────────────────────────
    ("education",           "certifications",             "includes", "Certifications",       "education--certifications"),
    ("education",           "training",                   "includes", "Leadership training",  "education--training"),
    ("certifications",      "iso-cert",                   "includes", "ISO 13485",             "certifications--iso-cert"),

    # ── Family hierarchy ──────────────────────────────────────────────────────
    ("family",              "family-personal",            "has",       "Private details",  "family--family-personal"),

    # ── Community → Engagements ───────────────────────────────────────────────
    ("community",           "engagements",                "includes", "Engagements",   "community--engagements"),

    # ── Earlier career → publication ──────────────────────────────────────────
    ("experience--earlier", "publication",                "authored",  "Academic publications", "earlier--publication"),

    # ── Personal life hub → personal detail nodes ─────────────────────────────
    ("personal--context", "personal--anecdotes",     "has", "Personal stories",          "personal--anecdotes-link"),
    ("personal--context", "personal--childhood",     "has", "Childhood & adolescence",   "personal--childhood-link"),
    ("personal--context", "personal--philips_years", "has", "Philips years (personal)",  "personal--philips-years-link"),

    # ── Cross-links (non-containment) ─────────────────────────────────────────
    ("cv",      "identity", "describes",  "Curriculum Vitae",              "cv--identity"),

    ("faq",     "identity", "describes",  "Frequently asked questions",   "faq--identity"),
    ("personality",         "disc",       "describes", "DISC profile",    "personality--disc"),
    ("personality",         "pldj",       "describes", "PLDJ",            "personality--pldj"),
    ("personal--philips_years", "experience--philips", "relates_to", "Personal side of Philips", "philips-personal--philips-exp"),
    ("personal--childhood", "education", "relates_to", "Foundation for education choices", "childhood--education"),
    ("projects--dromenbrouwer", "personal--context", "relates_to", "Family project", "dromenbrouwer--personal"),
]


def resync_seed_edges(db: "KnowledgeDB") -> None:
    """Delete all historically known seed edge IDs and re-insert the current set.

    Safe to call on every startup: only touches edges whose IDs are in the
    canonical seed list, leaving user-created edges (UUID ids) untouched.
    """
    now = datetime.now(timezone.utc).isoformat()
    with db._lock:
        existing_nodes = {
            r[0] for r in db._conn.execute("SELECT id FROM nodes").fetchall()
        }
        tombstoned = {
            r[0] for r in db._conn.execute("SELECT id FROM deleted_seed_edges").fetchall()
        }
        valid = [
            (eid, src, tgt, etype, label, json.dumps(["public"]), now)
            for src, tgt, etype, label, eid in _SEED_EDGES
            if src in existing_nodes and tgt in existing_nodes
            and eid not in tombstoned
        ]
        # Only remove+reinsert seed edges that are NOT tombstoned
        resync_ids = list(_ALL_SEEDED_IDS - tombstoned)
        placeholders = ",".join("?" * len(resync_ids))
        with db._conn:
            if resync_ids:
                db._conn.execute(
                    f"DELETE FROM edges WHERE id IN ({placeholders})",  # noqa: S608
                    resync_ids,
                )
            if valid:
                db._conn.executemany(
                    "INSERT OR IGNORE INTO edges "
                    "(id, source_id, target_id, type, label, roles, created_at) "
                    "VALUES (?,?,?,?,?,?,?)",
                    valid,
                )
    total = db._conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
    log.info(
        "resynced seed edges: %d canonical edges inserted, %d total edges in graph",
        len(valid), total,
    )


def apply_graph_customizations(db: KnowledgeDB) -> None:
    """Create extra nodes/edges that are not backed by markdown files.

    Idempotent — uses INSERT OR IGNORE.  Should be called after
    migrate_from_memory() and resync_seed_edges() on every startup.
    """
    now = datetime.now(timezone.utc).isoformat()

    CERTS_BODY = """\
# Certifications

## SAFe — Scaled Agile Framework
Certified during Philips era. The Value Stream Owner title is a SAFe concept.

## Lean Six Sigma Green Belt
Certified during Philips era.

## DAMA-DMBOK
Data management certification.

## O365 Forensics / eDiscovery
Microsoft certification, directly relevant to digital forensics work at FIOD.

## ISO 13485 — Quality Management System for Medical Devices
One-day training, Philips Eindhoven, 19 May 2017. Trainer: Peter Reijntjes (QServe Group). Certificate no. 17-1348.
"""

    TRAINING_BODY = """\
# Leadership Training

## De Baak — "Leidinggeven aan eigenwijze professionals"
Prestigious Dutch executive education institute. Focused on leading specialist and autonomous professionals.
Directly shaped leadership approach with expert teams and the broader hiring philosophy.
"""

    PUBLICATION_BODY = """\
# Publications

Peer-reviewed research publications by Sebastiaan den Boer.

## Journal of Cognitive Neuroscience (MSc era, Donders Institute)
**"Occipital Alpha and Gamma Oscillations Support Complementary Mechanisms for Processing Stimulus Value Associations"**
Tom R. Marshall, **Sebastiaan den Boer**, Roshan Cools, Ole Jensen, Sean James Fallon, Johanna M. Zumer.

## BMC Pregnancy and Childbirth (Philips era, 2018)
**"Evaluation of an activity monitor for use in pregnancy to help reduce excessive gestational weight gain"**
Paul M. C. Lemmens, Francesco Sartor, Lieke G. E. Cox, **Sebastiaan V. den Boer**, Joyce H. D. M. Westerink.
"""

    DISC_BODY = """\
# DISC Profile

DISC personality assessment results for Sebastiaan den Boer.

*Attach the DISC report PDF via the Knowledge admin interface.*

**Overview**: Dominant / Influential primary profile. High D + I scores indicate a results-oriented leader who is also persuasive and people-motivated.
"""

    PLDJ_BODY = """\
# PLDJ — Personal Leadership Document

Personal leadership reflection document.

*Attach the PLDJ PDF via the Knowledge admin interface.*
"""

    ISO_CERT_BODY = """\
# ISO 13485 Certificate

**ISO 13485: Quality Management System Requirements for Medical Devices**

- **Date**: 19 May 2017
- **Location**: Philips, Eindhoven
- **Trainer**: Peter Reijntjes (QServe Group)
- **Certificate no.**: 17-1348
"""

    FAMILY_PUBLIC_BODY = """\
# Family

Married to **Agnes**. Together since secondary school. Three kids:
**Else**, **Roos** (nicknamed "Roos Raket"), and **Tijmen**.

Based in De Bilt, Netherlands (Utrecht area).
"""

    FAMILY_PRIVATE_BODY = """\
# Family (Private)

Married to **Agnes den Boer** (b. 4 February 1990). Together since secondary school; married **20 September 2016**.

## Children
- **Else** (b. 30 August 2017)
- **Roos** (b. 19 February 2019, nicknamed "Roos Raket")
- **Tijmen** (b. 15 April 2022)

Home: De Bilt, Emmalaan 7, 3732 GM.
"""

    ENGAGEMENTS_BODY = """\
# Engagements

Structured overview of speaking engagements, conferences, and teaching.

## Annual Conferences

### aiGrunn (Groningen)
One of the more prominent AI events in the Netherlands.

| Year | Role |
|------|------|
| 2024 | Speaker — [Watch](https://www.youtube.com/watch?v=DmnfwWLpadc) |
| 2025 | Youwe sponsor; team presented (Erik Poolman: [local-first AI](https://www.youtube.com/watch?v=vVwr7NXBRbE); Jorn de Vreede: [ethics in AI](https://www.youtube.com/watch?v=qptQfIIAASo)) |
| 2026 | Co-organising the dedicated **business track** |

### Ecom Expo London — 24 September 2025
Keynote: *"Experience to the future: Stop selling products. Start selling experiences."*
The Optimisation Stage, 15:00–15:25.

## Enterprise Keynotes
- **Nutricia** — enterprise AI event
- **Kingspan** — enterprise AI event
- **aiGrunn** — every cycle (see above)

## aiGrunn Café (bi-monthly meetup)
Co-initiated with Jeroen Bos + Berco Beute. Venue: Youwe Groningen.
First edition: **5 February 2026** — 65 sign-ups + waitlist.
Topics: MCP, local models, sovereign AI.

## Guest Lecturing (regular)
- University of Groningen
- Nyenrode Business University
- Hogeschool Utrecht (HU)
- Saxion

## Expert Groups
- **ShoppingTomorrow — AI in Retail** (2024)

## Thought Leadership & Media
- **Alumio AI Playbook** — quoted on agentic AI. [alumio.com/alumio-ai-playbook](https://www.alumio.com/alumio-ai-playbook)
- **ABN AMRO** — expert quote on AI agents. [abnamro.nl](https://www.abnamro.nl/nl/zakelijk/insights/sectoren-en-trends/technologie/softwarebedrijven-nog-niet-klaar-voor-AI-agents.html)
- **CGM** — video appearance on AI in pharmacy/healthcare. [cgm.com](https://www.cgm.com/nld_nl/magazine/articles/video-hoe-gaat-ai-het-werk-in-de-apotheek-veranderen.htm)
- **Pimcore AI-Powered PXM** — co-presented webinar. [pimcore.com](https://pimcore.com/on-demand-webinar-ai-powered-pxm)

## Typical Topics
- Multi-agent systems in production (and how they fail)
- AI strategy for non-AI leadership teams
- The reality of building an AI practice from zero
- Pragmatic AI-assisted development workflows
"""

    CLIENTS_BODY = """\
# Clients (Confidential)

Actual client names for Youwe AI practice reference projects.
*Personal-tier only.*

| Project | Client | Status |
|---------|--------|--------|
| Pricing Engine (€80M/year margins) | Global agri-sciences company | Live in production |
| Travel Bot | Booking.com | Live in global production |
| Wellbeing Chatbot | Illumae / Intraconnection Group | Pilot (April 2026) |
| Order Processing | Kingspan | Enterprise (EU + UK) |
| Image Enhancement | Quooker | AI product imagery |
"""

    new_nodes = [
        ("nb-work",         "notebook",   "Work",              "",                ["public", "work"]),
        ("nb-personal",     "notebook",   "Personal",          "",                ["personal"]),
        ("certifications", "education",  "Certifications",    CERTS_BODY,        ["public", "work"]),
        ("training",        "education",  "Leadership Training", TRAINING_BODY,   ["public", "work"]),
        ("publication",     "document",   "Publications",      PUBLICATION_BODY,  ["public"]),
        ("disc",            "document",   "DISC",              DISC_BODY,         ["public", "work", "personal"]),
        ("pldj",            "document",   "PLDJ",              PLDJ_BODY,         ["public", "work", "personal"]),
        ("iso-cert",        "document",   "ISO 13485",         ISO_CERT_BODY,     ["public", "work"]),
        ("family",          "personal",   "Family",            FAMILY_PUBLIC_BODY, ["public"]),
        ("family-personal", "personal",   "Family (Private)",  FAMILY_PRIVATE_BODY, ["public", "work", "personal"]),
        ("engagements",     "community",  "Engagements",       ENGAGEMENTS_BODY,  ["public"]),
        ("clients",         "personal",   "Clients",           CLIENTS_BODY,      ["public", "work", "personal"]),
        # Individual publication nodes (originally created via document upload)
        ("8714656d-313b-4476-9b4d-ee3db0322f95", "document",
         "Evaluation of Activity Monitor in Pregnancy (BMC 2018)", "",            ["public", "work"]),
        ("43116815-686e-4afa-aae7-e8f63ec70815", "document",
         "AI in Retail: Hyperpersonalisatie (ShoppingTomorrow 2024)", "",          ["public", "work"]),
        ("3705e446-d1ca-4230-8508-42cf46b660da", "document",
         "EU AI Act Compliance Guide for eCommerce (Youwe 2025)", "",              ["public", "work"]),
    ]

    # Edges involving the new nodes — now handled by _SEED_EDGES / resync_seed_edges.
    # Only non-seed edges with specific role overrides go here.
    new_edges = [
        ("experience--philips",  "publication",            "authored",   "Philips publications",   ["public", "work"],            "philips--publication"),
        # Publication hub → individual publications
        ("publication", "8714656d-313b-4476-9b4d-ee3db0322f95", "includes", "Activity monitor pregnancy study (BMC 2018)",     ["public"],  "pub--bmc-2018"),
        ("publication", "43116815-686e-4afa-aae7-e8f63ec70815", "includes", "AI in retail hyperpersonalisatie (ShoppingTomorrow 2024)", ["public"], "pub--shopping-2024"),
        ("publication", "3705e446-d1ca-4230-8508-42cf46b660da", "includes", "EU AI Act compliance guide for eCommerce (Youwe 2025)",    ["public"], "pub--euai-2025"),
        # Experience → authored individual publications
        ("experience--philips", "8714656d-313b-4476-9b4d-ee3db0322f95", "authored", "Philips health research publication",     ["public", "work"], "philips--bmc-2018"),
        ("experience--youwe",   "43116815-686e-4afa-aae7-e8f63ec70815", "authored", "ShoppingTomorrow expert contribution",    ["public", "work"], "youwe--shopping-2024"),
        ("experience--youwe",   "3705e446-d1ca-4230-8508-42cf46b660da", "authored", "EU AI Act whitepaper (lead expert)",      ["public", "work"], "youwe--euai-2025"),
    ]

    # Notebook metadata for the four pillar nodes
    _notebook_meta = {
        "nb-work":      {"notebook_root": True, "icon": "💼", "order": 0},
        "education":    {"notebook_root": True, "icon": "🎓", "order": 1},
        "nb-personal":  {"notebook_root": True, "icon": "🏠", "order": 2},
        "hobbies":      {"notebook_root": True, "icon": "🎨", "order": 3},
    }

    with db._lock, db._conn:
        # Fix hobbies type
        db._conn.execute(
            "UPDATE nodes SET type = 'personal', updated_at = ? WHERE id = 'hobbies' AND type != 'personal'",
            (now,),
        )
        # Create new nodes
        for node_id, node_type, title, body, roles in new_nodes:
            meta = json.dumps(_notebook_meta.get(node_id, {}))
            db._conn.execute(
                "INSERT OR IGNORE INTO nodes "
                "(id, type, title, body, metadata, roles, created_at, updated_at) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (node_id, node_type, title, body, meta, json.dumps(roles), now, now),
            )
        # Ensure notebook metadata is set on promoted nodes (education, hobbies)
        for node_id, meta_patch in _notebook_meta.items():
            db._conn.execute(
                "UPDATE nodes SET metadata = json_patch(COALESCE(NULLIF(metadata,''),'{}'), json(?)), updated_at = ? "
                "WHERE id = ?",
                (json.dumps(meta_patch), now, node_id),
            )
        # Create edges involving new nodes
        for src, tgt, etype, label, roles, eid in new_edges:
            db._conn.execute(
                "INSERT OR IGNORE INTO edges "
                "(id, source_id, target_id, type, label, roles, created_at) "
                "VALUES (?,?,?,?,?,?,?)",
                (eid, src, tgt, etype, label, json.dumps(roles), now),
            )
        # Restore document metadata for nodes with known attached files
        known_docs = [
            ("cv",                 "documents/9de3bcbd.pdf",  "application/pdf", "CV_Sebastiaan_den_Boer.pdf"),
            ("iso-cert",           "documents/0fe91a92.pdf",  "application/pdf", "17-1348 ISO 13485 Sebastiaan Boer.pdf"),
            ("disc",               "documents/ce60a64b.pdf",  "application/pdf", "Insights Discovery - SebastiaandenBoer - 23 Motivating Director (Classic).pdf"),
            ("pldj",               "documents/e0261de5.pdf",  "application/pdf", "PLDJ - Life Journey.pdf"),
            ("publication",        "documents/dccb1e1b.pdf",  "application/pdf", "jocn_a_01185.pdf"),
            ("experience--philips","documents/7614f6d3.pdf",  "application/pdf", "s12884-018-1941-8.pdf"),
        ]
        for node_id, file_path, mime, original in known_docs:
            doc_meta = json.dumps({"file_path": file_path, "mime_type": mime, "original_filename": original})
            db._conn.execute(
                "UPDATE nodes SET metadata = json_patch(COALESCE(NULLIF(metadata,''),'{}'), json(?)) "
                "WHERE id = ? AND json_extract(COALESCE(NULLIF(metadata,''),'{}'), '$.file_path') IS NULL",
                (doc_meta, node_id),
            )
        # Keep engagements body up to date (richer content; INSERT OR IGNORE won't update)
        db._conn.execute(
            "UPDATE nodes SET body = ?, updated_at = ? WHERE id = 'engagements'",
            (ENGAGEMENTS_BODY, now),
        )

    total_nodes = db._conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
    total_edges = db._conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
    log.info("graph customizations applied: %d nodes, %d edges total", total_nodes, total_edges)


__all__ = [
    "KnowledgeDB",
    "KnowledgeNode",
    "KnowledgeEdge",
    "NODE_TYPES",
    "EDGE_TYPES",
    "CONTAINMENT_EDGE_TYPES",
    "CROSS_LINK_EDGE_TYPES",
    "is_containment",
    "migrate_from_memory",
    "resync_seed_edges",
    "apply_graph_customizations",
]
