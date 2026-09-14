#!/usr/bin/env python3
"""Create a public-only knowledge DB and Chroma index from the internal dataset."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "backend") not in sys.path:
    sys.path.insert(0, str(ROOT / "backend"))

from app.config import Settings, get_settings  # noqa: E402
from app.projection import publish_projection  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-db", default=None, help="Path to the internal knowledge.db")
    parser.add_argument("--target-db", required=True, help="Path to the published public knowledge.db")
    parser.add_argument("--target-chroma", required=True, help="Path to the published public Chroma directory")
    parser.add_argument(
        "--roles",
        nargs="+",
        default=["public"],
        help="Roles to publish into the projection (default: public)",
    )
    args = parser.parse_args()

    settings = get_settings()
    source_db = Path(args.source_db) if args.source_db else settings.knowledge_db_path
    target_db = Path(args.target_db)
    target_chroma = Path(args.target_chroma)

    counts = publish_projection(
        source_db_path=source_db,
        target_db_path=target_db,
        target_chroma_path=target_chroma,
        settings=settings,
        allowed_roles=args.roles,
        reindex_vectors=True,
    )
    print(json.dumps({
        "nodes": counts.nodes,
        "edges": counts.edges,
        "indexed_nodes": counts.indexed_nodes,
        "roles": args.roles,
        "target_db": str(target_db),
        "target_chroma": str(target_chroma),
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())