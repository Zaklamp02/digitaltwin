"""Groundwork export: only public notes reach the public state."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from app.groundwork import build_state, export_public_groundwork, is_public

PLAN = """---
visibility: {vis}
---
# Training Plan

| Date | Day | Run | Strength | Note |
| ---------- | --- | --- | -------- | ---- |
| 2026-10-27 | Tue | 9 km: 4×1 km @ 4:10 | TEST, A | Day 1 |
| 2026-11-01 | Sun | **Berenloop 10K** | A-light | |
| 2026-11-02 | Mon | Rest | — | |
"""

RUNS = """---
visibility: {vis}
---
| Date | Distance (km) | Duration | Avg Pace | Avg HR |
| ---------- | --- | --- | --- | --- |
| 2026-10-25 | 10.02 | 00:58:01 | 5:47 | 131 |
"""


def _vault(tmp_path: Path, plan_vis="public", runs_vis="public", config_vis="public") -> Path:
    sports = tmp_path / "Hobbies/Sports"
    (sports / "Groundwork").mkdir(parents=True)
    (sports / "Training Plan.md").write_text(PLAN.format(vis=plan_vis), encoding="utf-8")
    (sports / "Running Log.md").write_text(RUNS.format(vis=runs_vis), encoding="utf-8")
    (sports / "Groundwork/README.md").write_text(f"---\nvisibility: {config_vis}\n---\n# Groundwork data\n", encoding="utf-8")
    (sports / "Groundwork/sessions.json").write_text(json.dumps({"sessions": [{"id": "A", "name": "Back reset", "blocks": []}]}), encoding="utf-8")
    (sports / "Groundwork/settings.json").write_text(json.dumps({"locations": [], "prefs": {}}), encoding="utf-8")
    return tmp_path


def test_public_notes_are_exported(tmp_path: Path) -> None:
    state = build_state(_vault(tmp_path), today=date(2026, 10, 26))
    assert [p["date"] for p in state["plan"]] == ["2026-10-27", "2026-11-01", "2026-11-02"]
    assert state["plan"][0]["runKm"] == 9.0 and state["plan"][0]["strength"] == ["TEST", "A"]
    assert state["plan"][2]["rest"] and state["plan"][2]["strength"] == []
    assert state["races"] == [{"date": "2026-11-01", "event": "Berenloop", "distance": "10 km", "status": "Registered"}]
    assert state["runs"][0]["km"] == 10.02
    assert state["sessions"][0]["id"] == "A"
    assert state["readonly"] is True


def test_private_notes_are_skipped(tmp_path: Path) -> None:
    state = build_state(_vault(tmp_path, plan_vis="private", runs_vis="personal", config_vis="private"), today=date(2026, 10, 26))
    assert state["plan"] == [] and state["runs"] == [] and state["sessions"] == [] and state["settings"] == {}


def test_visibility_lists(tmp_path: Path) -> None:
    note = tmp_path / "n.md"
    note.write_text("---\nvisibility: [work, public]\n---\nx", encoding="utf-8")
    assert is_public(note)
    note.write_text("---\nvisibility: private\n---\nx", encoding="utf-8")
    assert not is_public(note)
    note.write_text("no frontmatter", encoding="utf-8")
    assert not is_public(note)


def test_export_writes_state_file(tmp_path: Path) -> None:
    vault = _vault(tmp_path / "vault")
    result = export_public_groundwork(vault, tmp_path / "out" / "groundwork")
    assert result["ok"]
    data = json.loads((tmp_path / "out/groundwork/state.json").read_text(encoding="utf-8"))
    assert data["plan"] and data["sessions"]
