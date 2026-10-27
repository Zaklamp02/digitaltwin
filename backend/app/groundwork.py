"""Publish the public data for the Groundwork training page (/groundwork/).

Like the family tree, this runs on the internal runtime after a vault sync and writes into the
public data dir, so the public runtime never reads the vault. Only notes whose frontmatter says
`visibility: public` are exported; anything else is skipped as if it did not exist.

Output: <target_dir>/state.json with the plan, recent runs, the strength log, and the routines and
settings for the app. The public backend serves it at /api/groundwork/state.
"""

from __future__ import annotations

import json
import re
from datetime import date, timedelta
from pathlib import Path

SPORTS = Path("Hobbies/Sports")
PLAN = SPORTS / "Training Plan.md"
RUNS = SPORTS / "Running Log.md"
STRENGTH = SPORTS / "Strength Log.md"
CONFIG_DIR = SPORTS / "Groundwork"
CONFIG_NOTE = CONFIG_DIR / "README.md"
RUN_HISTORY_DAYS = 150

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_FM_RE = re.compile(r"^---\s*\n(.*?)\n---", re.S)


def is_public(note: Path) -> bool:
    """True when the note exists and its frontmatter visibility includes 'public'."""
    if not note.is_file():
        return False
    m = _FM_RE.match(note.read_text(encoding="utf-8"))
    if not m:
        return False
    for line in m.group(1).splitlines():
        key, _, value = line.partition(":")
        if key.strip() == "visibility":
            value = value.strip().strip("[]")
            return "public" in [v.strip().strip("'\"") for v in value.split(",")]
    return False


def _table_rows(note: Path):
    for line in note.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if cells and _DATE_RE.match(cells[0]):
            yield cells


def _cell(cells: list[str], i: int) -> str:
    return cells[i] if i < len(cells) else ""


def parse_plan(note: Path) -> list[dict]:
    rows = []
    for c in _table_rows(note):
        run = _cell(c, 2)
        km = re.search(r"(\d+(?:[.,]\d+)?)\s*(?:–\s*\d+(?:[.,]\d+)?\s*)?km", run)
        race = re.search(r"\*\*(.+?)\*\*", run)
        strength = _cell(c, 3)
        rows.append({
            "date": c[0],
            "run": run.replace("**", ""),
            "runKm": float(km.group(1).replace(",", ".")) if km else None,
            "race": race.group(1) if race else None,
            "rest": run.lower().startswith("rest") or run in ("", "—", "-"),
            "strength": [s.strip() for s in re.split(r"[,+]", strength) if s.strip() and s.strip() not in ("—", "-")],
            "note": _cell(c, 4),
        })
    return sorted(rows, key=lambda r: r["date"])


def parse_runs(note: Path, today: date) -> list[dict]:
    since = (today - timedelta(days=RUN_HISTORY_DAYS)).isoformat()
    out = []
    for c in _table_rows(note):
        if c[0] < since:
            continue
        try:
            km = float(_cell(c, 1))
        except ValueError:
            continue
        out.append({"date": c[0], "km": km, "duration": _cell(c, 2), "pace": _cell(c, 3), "hr": _cell(c, 4)})
    return out


def parse_strength(note: Path) -> list[dict]:
    return [{"date": c[0], "session": _cell(c, 1), "minutes": _cell(c, 2), "effort": _cell(c, 3),
             "feel": _cell(c, 4), "location": _cell(c, 5), "done": _cell(c, 6), "note": _cell(c, 7)}
            for c in _table_rows(note)]


def races_from_plan(plan: list[dict], today: date) -> list[dict]:
    """Upcoming races are the plan's bold run entries (keeps the private race history out)."""
    out = []
    for p in plan:
        if p["race"] and p["date"] >= today.isoformat():
            dist = re.search(r"(\d+(?:[.,]\d+)?)\s*K\b", p["race"], re.I)
            out.append({"date": p["date"], "event": re.sub(r"\s*\d+(?:[.,]\d+)?\s*K\b", "", p["race"], flags=re.I).strip() or p["race"],
                        "distance": f"{dist.group(1)} km" if dist else "", "status": "Registered"})
    return out


def _read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def build_state(vault_root: Path, today: date | None = None) -> dict:
    today = today or date.today()
    plan_note, runs_note, strength_note = vault_root / PLAN, vault_root / RUNS, vault_root / STRENGTH
    plan = parse_plan(plan_note) if is_public(plan_note) else []
    config_public = is_public(vault_root / CONFIG_NOTE)
    return {
        "readonly": True,
        "plan": plan,
        "runs": parse_runs(runs_note, today) if is_public(runs_note) else [],
        "races": races_from_plan(plan, today),
        "strength": parse_strength(strength_note) if is_public(strength_note) else [],
        "sessions": _read_json(vault_root / CONFIG_DIR / "sessions.json", {"sessions": []})["sessions"] if config_public else [],
        "settings": _read_json(vault_root / CONFIG_DIR / "settings.json", {}) if config_public else {},
        "vault": None,
        "exportedAt": today.isoformat(),
    }


def export_public_groundwork(vault_root: Path, target_dir: Path) -> dict[str, object]:
    """Write state.json for the public Groundwork page. Returns a small status payload."""
    if not (vault_root / PLAN).exists():
        return {"ok": False, "status": "missing_source", "source": str(vault_root / PLAN), "target": str(target_dir)}
    state = build_state(vault_root)
    target_dir.mkdir(parents=True, exist_ok=True)
    tmp = target_dir / "state.json.tmp"
    tmp.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    tmp.replace(target_dir / "state.json")
    return {"ok": True, "status": "exported", "target": str(target_dir),
            "plan_days": len(state["plan"]), "runs": len(state["runs"]), "sessions": len(state["sessions"])}
