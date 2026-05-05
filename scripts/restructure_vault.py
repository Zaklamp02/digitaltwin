#!/usr/bin/env python3
"""Restructure the Obsidian vault:

1. Rename _index.md → folder notes (same name as parent folder, inside the folder)
2. Strip type-- prefixes from filenames (hobbies--booklist → booklist)
3. Promote Youwe to top-level notebook
4. Rename document PDFs to human-readable names
5. Update frontmatter: remove id/title/links, rename roles→visibility, default=personal
6. Convert frontmatter links: to [[wikilinks]] appended to body
7. Fix all [[wikilinks]] to match new filenames
"""

from __future__ import annotations

import re
import shutil
import yaml
from pathlib import Path

VAULT = Path.home() / "ObsidianVault" / "digital-twin"

# ── Document rename map (hash → human-readable) ──────────────────────────────

DOC_RENAMES = {
    "0fe91a92.pdf": "ISO 13485 Certificate.pdf",
    "236634e7.pdf": "236634e7.pdf",  # unmapped orphan — keep as-is
    "70c6d877.pdf": "Evaluation of Activity Monitor in Pregnancy (BMC 2018).pdf",
    "72ecf784.pdf": "EU AI Act Compliance Guide for eCommerce (Youwe 2025).pdf",
    "7614f6d3.pdf": "Activity Monitor Pregnancy (Philips copy).pdf",
    "85847ebd.pdf": "85847ebd.pdf",  # unmapped orphan — keep as-is
    "9de3bcbd.pdf": "CV Sebastiaan den Boer.pdf",
    "b550062c.pdf": "AI in Retail Hyperpersonalisatie (ShoppingTomorrow 2024).pdf",
    "ce60a64b.pdf": "Insights Discovery DISC Profile.pdf",
    "dccb1e1b.pdf": "Publications (jocn_a_01185).pdf",
    "e0261de5.pdf": "PLDJ Life Journey.pdf",
    "e6af208b.pdf": "FIOD Kerstpuzzel Opdrachten.pdf",
}

# ── Filename stripping rules ──────────────────────────────────────────────────

# Prefixes to strip from filenames (the folder already provides context)
STRIP_PREFIXES = [
    "hobbies--", "projects--", "personal--", "experience--",
    "community--", "education--", "family-",
]

def strip_prefix(name: str) -> str:
    """Strip type-- prefix from a filename stem."""
    for prefix in STRIP_PREFIXES:
        if name.startswith(prefix):
            return name[len(prefix):]
    return name


# ── Folder note conversion ────────────────────────────────────────────────────

def find_index_files(vault: Path) -> list[Path]:
    """Find all _index.md files."""
    return sorted(vault.rglob("_index.md"))


# ── Frontmatter processing ───────────────────────────────────────────────────

def parse_frontmatter(text: str) -> tuple[dict | None, str]:
    """Split file into (frontmatter_dict, body). Returns (None, text) if no frontmatter."""
    if not text.startswith("---"):
        return None, text
    end = text.find("\n---", 3)
    if end == -1:
        return None, text
    fm_text = text[4:end]
    body = text[end + 4:].lstrip("\n")
    try:
        fm = yaml.safe_load(fm_text)
        if not isinstance(fm, dict):
            return None, text
        return fm, body
    except yaml.YAMLError:
        return None, text


def build_frontmatter(fm: dict) -> str:
    """Build clean YAML frontmatter string."""
    lines = ["---"]
    for key in ["type", "visibility", "featured", "order"]:
        if key in fm and fm[key] is not None:
            val = fm[key]
            if isinstance(val, bool):
                lines.append(f"{key}: {'true' if val else 'false'}")
            elif isinstance(val, (int, float)):
                lines.append(f"{key}: {val}")
            else:
                lines.append(f"{key}: {val}")
    lines.append("---")
    return "\n".join(lines)


def extract_wikilink_targets(links_dict: dict) -> list[str]:
    """Extract wikilink targets from a frontmatter links: dict.
    
    e.g. {authored: ["[[foo]]", "[[bar]]"], relates_to: "[[baz]]"}
    → ["foo", "bar", "baz"]
    """
    targets = []
    for _edge_type, refs in links_dict.items():
        if isinstance(refs, str):
            refs = [refs]
        for ref in refs:
            m = re.match(r"\[\[(.+?)\]\]", ref.strip())
            if m:
                targets.append(m.group(1))
    return targets


# ── Main restructure ─────────────────────────────────────────────────────────

def main():
    vault = VAULT
    if not vault.exists():
        print(f"Vault not found: {vault}")
        return

    # Build a name mapping: old_stem → new_stem (for wikilink fixing)
    name_map: dict[str, str] = {}
    
    # Track all file moves: old_path → new_path (relative to vault)
    moves: list[tuple[Path, Path]] = []

    # ── Phase 1: Plan all renames ──────────────────────────────────────────

    print("Phase 1: Planning renames...")

    # 1a. Document renames
    docs_dir = vault / "documents"
    if docs_dir.exists():
        for old_name, new_name in DOC_RENAMES.items():
            old_path = docs_dir / old_name
            new_path = docs_dir / new_name
            if old_path.exists() and old_name != new_name:
                moves.append((old_path, new_path))
                print(f"  doc: {old_name} → {new_name}")

    # 1b. Promote Youwe: work/experience--youwe/ → youwe/
    youwe_old = vault / "work" / "experience--youwe"
    youwe_new = vault / "youwe"
    promote_youwe = youwe_old.exists()

    # 1c. Find all .md files and plan renames
    all_md = sorted(vault.rglob("*.md"))
    # Skip .obsidian and templates dirs
    all_md = [f for f in all_md if ".obsidian" not in f.parts and "templates" not in f.parts]

    for md_file in all_md:
        rel = md_file.relative_to(vault)
        old_stem = md_file.stem
        parts = list(rel.parts)

        # Skip root-level special files
        if len(parts) == 1 and parts[0] in ("_config.md", "_system.md", "Prep.md"):
            continue

        # _index.md → folder note (same name as parent folder)
        if md_file.name == "_index.md":
            parent_name = md_file.parent.name
            new_name = f"{parent_name}.md"
            new_path = md_file.parent / new_name
            name_map[old_stem] = parent_name  # _index → parent folder name for wikilinks
            # Also map the old id if it was something like "experience--youwe"
            moves.append((md_file, new_path))
            print(f"  folder note: {rel} → {rel.parent / new_name}")
            continue

        # Strip prefixes from filenames
        new_stem = strip_prefix(old_stem)
        if new_stem != old_stem:
            new_path = md_file.parent / f"{new_stem}.md"
            name_map[old_stem] = new_stem
            moves.append((md_file, new_path))
            print(f"  strip: {rel} → {rel.parent / f'{new_stem}.md'}")

    # Root _index.md → identity.md (special case)
    root_index = vault / "_index.md"
    if root_index.exists():
        name_map["_index"] = "identity"  # This is the identity node
        moves.append((root_index, vault / "identity.md"))
        print(f"  root: _index.md → identity.md")

    # 1d. Plan folder renames for stripped prefixes in directory names
    folder_renames: list[tuple[Path, Path]] = []
    for d in sorted(vault.rglob("*"), reverse=True):  # reverse to rename deepest first
        if not d.is_dir() or ".obsidian" in d.parts or "templates" in d.parts:
            continue
        old_name = d.name
        new_name = strip_prefix(old_name)
        if new_name != old_name:
            new_path = d.parent / new_name
            folder_renames.append((d, new_path))
            print(f"  folder: {d.relative_to(vault)} → {d.parent.relative_to(vault) / new_name}")

    # ── Phase 2: Execute document renames ──────────────────────────────────
    print("\nPhase 2: Renaming documents...")
    for old_path, new_path in moves:
        if old_path.parent.name == "documents" and old_path.suffix == ".pdf":
            if old_path.exists():
                new_path.parent.mkdir(parents=True, exist_ok=True)
                old_path.rename(new_path)
                print(f"  ✓ {old_path.name} → {new_path.name}")

    # ── Phase 3: Promote Youwe ─────────────────────────────────────────────
    if promote_youwe:
        print("\nPhase 3: Promoting Youwe to top-level...")
        if youwe_new.exists():
            shutil.rmtree(youwe_new)
        shutil.move(str(youwe_old), str(youwe_new))
        print(f"  ✓ work/experience--youwe/ → youwe/")
        # Update name_map for the youwe _index
        name_map["experience--youwe"] = "youwe"
    
    # ── Phase 4: Execute .md file renames ──────────────────────────────────
    print("\nPhase 4: Renaming markdown files...")
    # Filter out already-moved files and doc renames
    md_moves = [(o, n) for o, n in moves if o.suffix == ".md"]
    for old_path, new_path in md_moves:
        # Update path if parent was moved (Youwe promotion)
        if promote_youwe and "experience--youwe" in str(old_path):
            old_path = Path(str(old_path).replace(str(youwe_old), str(youwe_new)))
        if old_path.exists():
            new_path_actual = Path(str(new_path).replace(str(youwe_old), str(youwe_new))) if promote_youwe else new_path
            new_path_actual.parent.mkdir(parents=True, exist_ok=True)
            old_path.rename(new_path_actual)
            print(f"  ✓ {old_path.relative_to(vault)} → {new_path_actual.relative_to(vault)}")

    # ── Phase 5: Rename folders with stripped prefixes ─────────────────────
    print("\nPhase 5: Renaming folders...")
    for old_dir, new_dir in folder_renames:
        # Check if it still exists (may have been moved by Youwe promotion)
        if promote_youwe:
            old_dir = Path(str(old_dir).replace(str(youwe_old), str(youwe_new)))
            new_dir = Path(str(new_dir).replace(str(youwe_old), str(youwe_new)))
        if old_dir.exists() and not new_dir.exists():
            old_dir.rename(new_dir)
            print(f"  ✓ {old_dir.name} → {new_dir.name}")

    # ── Phase 6: Build final name map from actual files ────────────────────
    print("\nPhase 6: Building wikilink name map...")
    # Scan all .md files in the vault to build stem → new_stem map
    final_stems = set()
    for md_file in vault.rglob("*.md"):
        if ".obsidian" not in str(md_file) and "templates" not in str(md_file):
            final_stems.add(md_file.stem)

    # Add identity/folder note mappings
    # Old IDs that mapped to folder names via _index.md
    old_id_map = {}
    for md_file in vault.rglob("*.md"):
        if ".obsidian" in str(md_file) or "templates" in str(md_file):
            continue
        rel = md_file.relative_to(vault)
        fm, _ = parse_frontmatter(md_file.read_text(encoding="utf-8"))
        if fm and fm.get("id"):
            old_id = fm["id"]
            new_stem = md_file.stem
            if old_id != new_stem:
                name_map[old_id] = new_stem
                old_id_map[old_id] = new_stem

    print(f"  {len(name_map)} name mappings built")
    for old, new in sorted(name_map.items()):
        if old != new:
            print(f"    {old} → {new}")

    # ── Phase 7: Update all frontmatter and wikilinks ──────────────────────
    print("\nPhase 7: Updating frontmatter and wikilinks...")
    updated = 0
    for md_file in sorted(vault.rglob("*.md")):
        if ".obsidian" in str(md_file) or "templates" in str(md_file):
            continue

        text = md_file.read_text(encoding="utf-8")
        fm, body = parse_frontmatter(text)

        new_text_parts = []
        changed = False

        # Process frontmatter
        if fm:
            new_fm = {}
            # Keep type
            if fm.get("type"):
                new_fm["type"] = fm["type"]
            # Convert roles → visibility (skip if roles == ["public"] since that needs explicit visibility)
            roles = fm.get("roles", [])
            if isinstance(roles, str):
                roles = [roles]
            if roles and roles != ["public"]:
                # Non-public roles → keep as personal (default, omit)
                pass
            elif roles == ["public"]:
                new_fm["visibility"] = "public"
            # Keep featured
            if fm.get("featured"):
                new_fm["featured"] = True
            # Keep order
            if "order" in fm and fm["order"] is not None:
                new_fm["order"] = fm["order"]

            # Extract links: for conversion to wikilinks in body
            links_targets = []
            if fm.get("links"):
                links_targets = extract_wikilink_targets(fm["links"])
            
            # Remove: id, title, links, roles (replaced by visibility)

            # Build new frontmatter
            fm_str = build_frontmatter(new_fm)
            
            # Add see-also section for old links: if any
            if links_targets:
                # Map old link targets to new names
                mapped_links = []
                for target in links_targets:
                    new_target = name_map.get(target, target)
                    # Also try stripping prefixes
                    if new_target == target:
                        new_target = strip_prefix(target)
                    mapped_links.append(new_target)
                
                see_also = "\n\n---\n**See also:** " + " · ".join(f"[[{t}]]" for t in mapped_links) + "\n"
                body = body.rstrip() + see_also

            new_text_parts.append(fm_str)
            new_text_parts.append("\n")
            new_text_parts.append(body)
            changed = True
        else:
            new_text_parts.append(text)

        new_text = "".join(new_text_parts)

        # Fix wikilinks in body: replace old stems with new stems
        def replace_wikilink(m):
            target = m.group(1)
            # Handle display text: [[target|display]]
            display = ""
            if "|" in target:
                target, display = target.split("|", 1)
                display = "|" + display
            new_target = name_map.get(target, target)
            if new_target == target:
                new_target = strip_prefix(target)
            if new_target != target:
                nonlocal changed
                changed = True
            return f"[[{new_target}{display}]]"

        new_text = re.sub(r"\[\[([^\]]+)\]\]", replace_wikilink, new_text)

        if changed:
            md_file.write_text(new_text, encoding="utf-8")
            updated += 1

    print(f"  ✓ {updated} files updated")

    # ── Phase 8: Summary ───────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("RESTRUCTURE COMPLETE")
    print("=" * 60)
    final_count = sum(1 for _ in vault.rglob("*.md") if ".obsidian" not in str(_) and "templates" not in str(_))
    final_folders = sum(1 for d in vault.rglob("*") if d.is_dir() and ".obsidian" not in str(d) and "templates" not in str(d))
    final_docs = sum(1 for _ in (vault / "documents").rglob("*.pdf")) if (vault / "documents").exists() else 0
    print(f"  {final_count} markdown files")
    print(f"  {final_folders} folders")
    print(f"  {final_docs} document PDFs")
    print(f"\nVault: {vault}")


if __name__ == "__main__":
    main()
