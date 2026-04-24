#!/usr/bin/env python3
"""Seed the four-notebook pillar structure into the knowledge graph.

Idempotent — safe to re-run. Reads/writes through KnowledgeDB helpers.

Creates:
  - nb-work (new)          → Work
  - education (promoted)   → Education
  - nb-personal (new)      → Personal
  - hobbies (promoted)     → Hobbies

Rewires existing level-1 nodes under the appropriate pillar.
Places document-type nodes into the tree via containment edges.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

# Ensure backend package is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.knowledge import KnowledgeDB, CONTAINMENT_EDGE_TYPES  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
log = logging.getLogger("seed")

# ── configuration ─────────────────────────────────────────────────────────────

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "knowledge.db"

# The four notebook roots
NOTEBOOKS = [
    {
        "id": "nb-work",
        "title": "Work",
        "icon": "💼",
        "roles": ["public", "recruiter"],
        "type": "notebook",
        "action": "create",
        "order": 0,
    },
    {
        "id": "education",
        "title": "Education",
        "icon": "🎓",
        "roles": None,  # keep existing
        "type": None,    # keep existing
        "action": "promote",
        "order": 1,
    },
    {
        "id": "nb-personal",
        "title": "Personal",
        "icon": "🏠",
        "roles": ["personal"],
        "type": "notebook",
        "action": "create",
        "order": 2,
    },
    {
        "id": "hobbies",
        "title": "Hobbies",
        "icon": "🎨",
        "roles": None,  # keep existing
        "type": None,    # keep existing
        "action": "promote",
        "order": 3,
    },
]

# identity → notebook-root edges (type=has)
IDENTITY_EDGES = [
    ("identity", "nb-work",      "has", "Work"),
    ("identity", "education",    "has", "Education"),
    ("identity", "nb-personal",  "has", "Personal"),
    ("identity", "hobbies",      "has", "Hobbies"),
]

# Level-1 nodes to rewire under the appropriate notebook
REWIRE = [
    # (child_id, new_parent_id, edge_type, label)
    ("career",           "nb-work",      "includes", "Career"),
    ("community",        "nb-work",      "includes", "Community"),
    ("publication",      "nb-work",      "includes", "Publications"),
    ("stack",            "nb-work",      "includes", "Tech Stack"),
    ("faq",              "nb-work",      "includes", "FAQ"),
    ("personality",      "nb-personal",  "includes", "Personality"),
    ("personal--context","nb-personal",  "includes", "Personal Life"),
    ("family",           "nb-personal",  "includes", "Family"),
]

# Document nodes to place into the tree (containment edges)
DOCUMENT_PLACEMENT = [
    ("nb-work",      "cv",     "includes", "CV"),
    ("nb-work",      "images", "includes", "Images"),
    ("personality",  "disc",   "includes", "DISC profile"),
    ("personality",  "pldj",   "includes", "PLDJ"),
    # publication is already wired above in REWIRE
    # iso-cert already has certifications --includes--> iso-cert
]

# Project nodes under Youwe that currently only have `built` edges —
# add explicit includes edges so they appear in the tree
PROJECT_PLACEMENT = [
    ("experience--youwe", "projects--pricing-engine",  "includes", "Pricing Engine"),
    ("experience--youwe", "projects--travel-bot",      "includes", "Travel Bot"),
    ("experience--youwe", "projects--product-platform", "includes", "Product Platform"),
]

# ── helpers ───────────────────────────────────────────────────────────────────


def _edge_exists(db: KnowledgeDB, source_id: str, target_id: str, edge_type: str) -> bool:
    """Check if an edge already exists."""
    edges = db.list_edges(node_id=source_id)
    return any(
        e.source_id == source_id and e.target_id == target_id and e.type == edge_type
        for e in edges
    )


def _ensure_edge(db: KnowledgeDB, source_id: str, target_id: str, edge_type: str, label: str) -> None:
    """Create edge if it doesn't already exist."""
    if _edge_exists(db, source_id, target_id, edge_type):
        log.info("  edge exists: %s --%s--> %s", source_id, edge_type, target_id)
        return
    db.create_edge(source_id=source_id, target_id=target_id, type=edge_type, label=label)
    log.info("  created edge: %s --%s--> %s (%s)", source_id, edge_type, target_id, label)


def _remove_identity_containment(db: KnowledgeDB, child_id: str) -> None:
    """Remove direct identity → child containment edges that conflict with new model.

    Only removes containment edges from identity; preserves cross-links.
    """
    edges = db.list_edges(node_id="identity")
    for e in edges:
        if e.source_id == "identity" and e.target_id == child_id and e.type in CONTAINMENT_EDGE_TYPES:
            # Don't delete the 'has' edges we just created for notebook roots
            if child_id in ("nb-work", "education", "nb-personal", "hobbies"):
                continue
            db.delete_edge(e.id)
            log.info("  removed: identity --%s--> %s", e.type, child_id)
        elif e.target_id == "identity" and e.source_id == child_id and e.type in CONTAINMENT_EDGE_TYPES:
            if child_id in ("nb-work", "education", "nb-personal", "hobbies"):
                continue
            db.delete_edge(e.id)
            log.info("  removed: %s --%s--> identity", child_id, e.type)


# ── main ──────────────────────────────────────────────────────────────────────


def seed(db: KnowledgeDB) -> None:
    log.info("=== Step 1: Establish four notebook roots ===")
    for nb in NOTEBOOKS:
        existing = db.get_node(nb["id"])
        if nb["action"] == "create":
            if existing:
                log.info("  %s already exists — updating metadata", nb["id"])
                meta = existing.metadata.copy()
                meta["notebook_root"] = True
                meta["icon"] = nb["icon"]
                meta["order"] = nb["order"]
                db.update_node(nb["id"], metadata=meta, type=nb["type"])
            else:
                log.info("  creating %s (%s)", nb["id"], nb["title"])
                node = db.create_node(
                    id=nb["id"],
                    type=nb["type"],
                    title=nb["title"],
                    body="",
                    roles=nb["roles"],
                    metadata={
                        "notebook_root": True,
                        "icon": nb["icon"],
                        "order": nb["order"],
                    },
                )
                log.info("  created node: %s", node.id)
        elif nb["action"] == "promote":
            if not existing:
                log.error("  %s does not exist — cannot promote!", nb["id"])
                continue
            log.info("  promoting %s to notebook root", nb["id"])
            meta = existing.metadata.copy()
            meta["notebook_root"] = True
            meta["icon"] = nb["icon"]
            meta["order"] = nb["order"]
            db.update_node(nb["id"], metadata=meta)

    log.info("\n=== Step 2: Ensure identity → notebook-root edges ===")
    for source, target, etype, label in IDENTITY_EDGES:
        _ensure_edge(db, source, target, etype, label)

    log.info("\n=== Step 3: Rewire level-1 nodes under notebooks ===")
    for child_id, new_parent_id, edge_type, label in REWIRE:
        child = db.get_node(child_id)
        if not child:
            log.warning("  node %s not found — skipping", child_id)
            continue
        _ensure_edge(db, new_parent_id, child_id, edge_type, label)

    log.info("\n=== Step 4: Remove old identity → level-1 containment edges ===")
    for child_id, _, _, _ in REWIRE:
        _remove_identity_containment(db, child_id)

    log.info("\n=== Step 5: Place document nodes into the tree ===")
    for parent_id, child_id, edge_type, label in DOCUMENT_PLACEMENT:
        child = db.get_node(child_id)
        if not child:
            log.warning("  node %s not found — skipping", child_id)
            continue
        _ensure_edge(db, parent_id, child_id, edge_type, label)

    log.info("\n=== Step 6: Add explicit includes edges for Youwe projects ===")
    for parent_id, child_id, edge_type, label in PROJECT_PLACEMENT:
        child = db.get_node(child_id)
        if not child:
            log.warning("  node %s not found — skipping", child_id)
            continue
        _ensure_edge(db, parent_id, child_id, edge_type, label)

    log.info("\n=== Step 7: Verify invariants ===")
    _verify(db)

    log.info("\n✅ Seed complete.")


def _verify(db: KnowledgeDB) -> None:
    """Verify every non-identity node reaches identity through containment."""
    nodes = db.list_nodes()
    edges = db.list_edges()

    node_ids = {n.id for n in nodes}
    notebook_ids = {n.id for n in nodes if n.metadata.get("notebook_root")}

    # Build parent map (child -> set of parents) from containment edges
    parents_of: dict[str, set[str]] = {}
    for e in edges:
        if e.type in CONTAINMENT_EDGE_TYPES:
            if e.type in ("member_of", "studied_at"):
                parent, child = e.target_id, e.source_id
            else:
                parent, child = e.source_id, e.target_id
            parents_of.setdefault(child, set()).add(parent)

    # Check each node can reach identity
    orphans = []
    for n in nodes:
        if n.id == "identity" or n.type == "system":
            continue
        visited: set[str] = set()
        stack = [n.id]
        reached_identity = False
        while stack:
            nid = stack.pop()
            if nid in visited:
                continue
            visited.add(nid)
            if nid == "identity":
                reached_identity = True
                break
            for p in parents_of.get(nid, set()):
                stack.append(p)
        if not reached_identity:
            orphans.append(n.id)

    if orphans:
        log.warning("⚠️  Orphan nodes (no path to identity): %s", orphans)
    else:
        log.info("  ✅ All nodes reach identity through containment edges.")

    # Check notebook roots
    log.info("  Notebook roots: %s", sorted(notebook_ids))
    if len(notebook_ids) != 4:
        log.warning("  ⚠️  Expected 4 notebook roots, found %d", len(notebook_ids))


if __name__ == "__main__":
    if not DB_PATH.exists():
        log.error("Database not found: %s", DB_PATH)
        sys.exit(1)
    log.info("Opening %s", DB_PATH)
    db = KnowledgeDB(DB_PATH)
    try:
        seed(db)
    finally:
        db.close()
