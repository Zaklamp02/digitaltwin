#!/usr/bin/env python3
"""Reverse the notebook-structure seed: drop synthetic nodes and restore
identity → level-1 containment edges.

Idempotent — safe to re-run.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.knowledge import KnowledgeDB, CONTAINMENT_EDGE_TYPES  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
log = logging.getLogger("unseed")

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "knowledge.db"

# Synthetic nodes to remove
SYNTHETIC_NODES = ["nb-work", "nb-personal"]

# Promoted nodes to demote (remove notebook_root flag)
PROMOTED_NODES = ["education", "hobbies"]

# Edges to restore: identity → level-1 nodes (original structure)
RESTORE_EDGES = [
    ("identity", "career",          "has",         "Career"),
    ("identity", "community",       "member_of",   "Community"),
    ("identity", "personality",     "describes",   "Personality"),
    ("identity", "personal--context","has",         "Personal life"),
    ("identity", "faq",             "describes",   "Common questions"),
    ("identity", "family",          "has",         "Family"),
    ("identity", "certifications",  "studied_at",  "Certifications"),
    ("identity", "publication",     "authored",    "Publications"),
]

# Explicit includes edges added by seed that should be removed
ADDED_INCLUDES = [
    ("nb-work",          "career",                    "includes"),
    ("nb-work",          "community",                 "includes"),
    ("nb-work",          "publication",               "includes"),
    ("nb-work",          "stack",                     "includes"),
    ("nb-work",          "faq",                       "includes"),
    ("nb-work",          "cv",                        "includes"),
    ("nb-work",          "images",                    "includes"),
    ("nb-personal",      "personality",               "includes"),
    ("nb-personal",      "personal--context",         "includes"),
    ("nb-personal",      "family",                    "includes"),
    ("personality",      "disc",                      "includes"),
    ("personality",      "pldj",                      "includes"),
    ("experience--youwe","projects--pricing-engine",   "includes"),
    ("experience--youwe","projects--travel-bot",       "includes"),
    ("experience--youwe","projects--product-platform", "includes"),
]


def unseed(db: KnowledgeDB) -> None:
    log.info("=== Step 1: Remove edges added by seed ===")
    edges = db.list_edges()
    for src, tgt, etype in ADDED_INCLUDES:
        for e in edges:
            if e.source_id == src and e.target_id == tgt and e.type == etype:
                db.delete_edge(e.id)
                log.info("  removed: %s --%s--> %s", src, etype, tgt)

    log.info("\n=== Step 2: Remove identity → notebook-root 'has' edges ===")
    edges = db.list_edges(node_id="identity")
    for e in edges:
        if e.source_id == "identity" and e.target_id in ("nb-work", "nb-personal") and e.type == "has":
            db.delete_edge(e.id)
            log.info("  removed: identity --has--> %s", e.target_id)
        # Also remove identity --has--> education/hobbies if they were added by seed
        if e.source_id == "identity" and e.target_id in ("education", "hobbies") and e.type == "has":
            db.delete_edge(e.id)
            log.info("  removed: identity --has--> %s", e.target_id)

    log.info("\n=== Step 3: Delete synthetic nodes ===")
    for nid in SYNTHETIC_NODES:
        node = db.get_node(nid)
        if node:
            db.delete_node(nid)
            log.info("  deleted node: %s", nid)
        else:
            log.info("  %s does not exist — skip", nid)

    log.info("\n=== Step 4: Demote promoted nodes ===")
    for nid in PROMOTED_NODES:
        node = db.get_node(nid)
        if node:
            meta = node.metadata.copy()
            meta.pop("notebook_root", None)
            meta.pop("icon", None)
            meta.pop("order", None)
            db.update_node(nid, metadata=meta)
            log.info("  demoted %s", nid)

    log.info("\n=== Step 5: Restore original identity → level-1 edges ===")
    for src, tgt, etype, label in RESTORE_EDGES:
        if db.get_node(tgt):
            db.create_edge(source_id=src, target_id=tgt, type=etype, label=label)
            log.info("  restored: %s --%s--> %s", src, etype, tgt)

    log.info("\n✅ Unseed complete.")


if __name__ == "__main__":
    if not DB_PATH.exists():
        log.error("Database not found: %s", DB_PATH)
        sys.exit(1)
    log.info("Opening %s", DB_PATH)
    db = KnowledgeDB(DB_PATH)
    try:
        unseed(db)
    finally:
        db.close()
