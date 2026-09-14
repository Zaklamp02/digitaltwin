"""Helpers for publishing the public family tree site from the vault."""

from __future__ import annotations

import shutil
from pathlib import Path


FAMILY_TREE_SOURCE_RELATIVE = Path("Personal/Family/Stamboom/Stamboom Boomdiagram.html")
FAMILY_TREE_SOURCES_DIRNAME = "Stamboom Sources"


def export_public_family_tree(vault_root: Path, target_dir: Path) -> dict[str, object]:
    """Publish the family tree HTML and sibling source files into a public dir.

    Returns a small status payload for logging/debugging.
    """
    source = (vault_root / FAMILY_TREE_SOURCE_RELATIVE).resolve()
    if not source.exists() or not source.is_file():
        return {
            "ok": False,
            "status": "missing_source",
            "source": str(source),
            "target": str(target_dir),
        }

    source_dir = source.parent
    source_assets_dir = source_dir / FAMILY_TREE_SOURCES_DIRNAME

    if target_dir.exists():
        shutil.rmtree(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)

    target_index = target_dir / "index.html"
    shutil.copy2(source, target_index)

    assets_copied = False
    if source_assets_dir.exists() and source_assets_dir.is_dir():
        shutil.copytree(source_assets_dir, target_dir / FAMILY_TREE_SOURCES_DIRNAME)
        assets_copied = True

    return {
        "ok": True,
        "status": "copied",
        "source": str(source),
        "target": str(target_dir),
        "index": str(target_index),
        "assets_dir": str(source_assets_dir),
        "assets_copied": assets_copied,
    }
