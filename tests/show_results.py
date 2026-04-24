"""Show and compare golden Q&A test results.

Usage:
    # Show latest run (compact)
    python tests/show_results.py

    # Show a specific run
    python tests/show_results.py logs/golden_results_gpt-4o.json

    # Show with full response text + chunk details per case
    python tests/show_results.py --verbose

    # Show only failures
    python tests/show_results.py --failures-only

    # Diff two runs — regressions, fixes, and response changes
    python tests/show_results.py logs/golden_results_a.json logs/golden_results_b.json

    # List all saved runs with their metadata
    python tests/show_results.py --list
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
LOGS_DIR = ROOT / "logs"
DEFAULT_FILE = LOGS_DIR / "golden_results_latest.json"

_W_ID = 8
_W_PERSONA = 10
_W_TIER = 10
_W_LAT = 7
_W_CHUNKS = 7


def _col(s: str | int, width: int) -> str:
    s = str(s)
    return s[:width].ljust(width)


def _trunc(s: str, n: int) -> str:
    s = s.replace("\n", " ").replace("\r", "")
    return (s[: n - 1] + "…") if len(s) > n else s


def _load(path: Path) -> dict:
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def _envelope_line(data: dict) -> str:
    parts = [
        f"model={data.get('model', '?')}",
        f"provider={data.get('provider', '?')}",
    ]
    if data.get("label"):
        parts.insert(0, f"label={data['label']}")
    return "  ".join(parts)


# ── single-run report ─────────────────────────────────────────────────────────


def show(path: Path, *, verbose: bool = False, failures_only: bool = False) -> None:
    data = _load(path)
    cases = data.get("cases", [])

    passed = sum(1 for c in cases if c.get("passed"))
    total = len(cases)
    total_lat = sum(c.get("latency_ms", 0) for c in cases)
    pct = f"{100 * passed / total:.0f}%" if total else "-%"

    print()
    print(f"Golden Q&A Results — {data.get('run_at', '?')}")
    print(f"  {_envelope_line(data)}")
    print(f"  url: {data.get('base_url', '?')}")
    print(f"  score: {passed}/{total} ({pct})  |  {total_lat / 1000:.1f}s total")
    print()

    W_PREV = 60 if verbose else 80
    sep_len = _W_ID + _W_PERSONA + _W_TIER + 6 + _W_LAT + _W_CHUNKS + W_PREV + 6
    sep = "-" * sep_len
    hdr = (
        _col("ID", _W_ID) + "  "
        + _col("PERSONA", _W_PERSONA) + "  "
        + _col("TIER", _W_TIER)
        + "  ST  "
        + _col("LAT ms", _W_LAT) + "  "
        + _col("CHUNKS", _W_CHUNKS) + "  RESPONSE"
    )
    print(hdr)
    print(sep)

    for c in cases:
        if failures_only and c.get("passed"):
            continue

        status = "OK" if c.get("passed") else "FAIL"
        preview_src = c.get("error") or c.get("response") or ""
        preview = _trunc(preview_src, W_PREV)

        print(
            _col(c.get("id", "?"), _W_ID) + "  "
            + _col(c.get("persona", "?"), _W_PERSONA) + "  "
            + _col(c.get("tier", "?"), _W_TIER)
            + f"  {status:4}  "
            + _col(c.get("latency_ms", 0), _W_LAT) + "  "
            + _col(c.get("chunks_retrieved", 0), _W_CHUNKS)
            + f"  {preview}"
        )

        if not c.get("passed"):
            indent = " " * (_W_ID + _W_PERSONA + _W_TIER + 18)
            for miss in c.get("keyword_misses", []):
                print(f"{indent}missing: \"{miss}\"")
            for hit in c.get("forbidden_hits", []):
                print(f"{indent}FORBIDDEN: \"{hit}\"")

        if verbose:
            resp = (c.get("response") or "").strip()
            if resp:
                for line in resp.split("\n"):
                    print(f"  {'':>{_W_ID}}  {line}")
            chunks = c.get("chunks") or []
            if chunks:
                print(f"  {'':>{_W_ID}}  Retrieved chunks:")
                for ch in chunks:
                    score = ch.get("score", 0)
                    print(
                        f"  {'':>{_W_ID}}    [{ch.get('tier','?'):10}] "
                        f"{score:.3f}  {ch.get('file','?')}  s{ch.get('section','')}"
                    )
            print()

    print()

    failures = [c for c in cases if not c.get("passed")]
    if failures and not verbose:
        print("--- FAILURE DETAIL " + "-" * 60)
        for c in failures:
            print(f"\n[{c.get('id')}] {c.get('question')!r}")
            if c.get("error"):
                print(f"  ERROR  : {c['error']}")
            else:
                resp = (c.get("response") or "").strip()
                print(f"  RESPONSE: {resp[:600]!r}")
            chunks = c.get("chunks") or []
            if chunks:
                print(f"  CHUNKS ({len(chunks)}):")
                for ch in chunks:
                    print(f"    [{ch.get('tier','?'):10}] {ch.get('score',0):.3f}  "
                          f"{ch.get('file','?')}  s{ch.get('section','')}")
            for miss in c.get("keyword_misses", []):
                print(f"  missing: \"{miss}\"")
            for hit in c.get("forbidden_hits", []):
                print(f"  FORBIDDEN: \"{hit}\"")
        print()


# ── diff report ───────────────────────────────────────────────────────────────


def diff(path_a: Path, path_b: Path) -> None:
    a = _load(path_a)
    b = _load(path_b)

    a_by_id = {c["id"]: c for c in a.get("cases", []) if "id" in c}
    b_by_id = {c["id"]: c for c in b.get("cases", []) if "id" in c}
    all_ids = list(a_by_id) + [i for i in b_by_id if i not in a_by_id]

    regressions: list[tuple] = []
    fixes: list[tuple] = []
    unchanged_pass: list[str] = []
    unchanged_fail: list[str] = []

    for cid in all_ids:
        ca = a_by_id.get(cid)
        cb = b_by_id.get(cid)
        if ca is None:
            fixes.append((cid, "new", ca, cb))
        elif cb is None:
            regressions.append((cid, "removed", ca, cb))
        elif ca.get("passed") and not cb.get("passed"):
            regressions.append((cid, "regression", ca, cb))
        elif not ca.get("passed") and cb.get("passed"):
            fixes.append((cid, "fixed", ca, cb))
        elif cb.get("passed"):
            unchanged_pass.append(cid)
        else:
            unchanged_fail.append(cid)

    print()
    print(f"Diff: {path_a.name}  ->  {path_b.name}")
    print(f"  A: {a.get('run_at', '?')}  {_envelope_line(a)}")
    print(f"  B: {b.get('run_at', '?')}  {_envelope_line(b)}")

    a_pass = sum(1 for c in a["cases"] if c.get("passed"))
    b_pass = sum(1 for c in b["cases"] if c.get("passed"))
    delta = b_pass - a_pass
    delta_str = f"+{delta}" if delta > 0 else str(delta)
    print(f"  Score: {a_pass}/{len(a['cases'])}  ->  {b_pass}/{len(b['cases'])}  ({delta_str})")
    print()

    if regressions:
        print("REGRESSIONS (was passing, now failing):")
        for cid, reason, ca, cb in regressions:
            c = cb or ca or {}
            print(f"\n  [{cid}] {c.get('question', '')!r}")
            for miss in (cb or {}).get("keyword_misses", []):
                print(f"    missing: \"{miss}\"")
            for hit in (cb or {}).get("forbidden_hits", []):
                print(f"    FORBIDDEN: \"{hit}\"")
            _print_side_by_side(ca, cb)
        print()

    if fixes:
        print("FIXES (was failing, now passing):")
        for cid, reason, ca, cb in fixes:
            c = cb or ca or {}
            print(f"\n  [{cid}] {c.get('question', '')!r}")
            _print_side_by_side(ca, cb)
        print()

    if unchanged_fail:
        print(f"STILL FAILING ({len(unchanged_fail)}): {', '.join(unchanged_fail)}")
        print()

    # Flag passing cases where the response changed substantially
    changed: list[tuple[str, str, str]] = []
    for cid in unchanged_pass:
        ca = a_by_id.get(cid)
        cb = b_by_id.get(cid)
        if ca and cb:
            ra = (ca.get("response") or "").strip()
            rb = (cb.get("response") or "").strip()
            if ra != rb and abs(len(ra) - len(rb)) > 30:
                changed.append((cid, ra, rb))

    if changed:
        print(f"RESPONSE CHANGES in passing cases ({len(changed)}):")
        for cid, ra, rb in changed:
            ca = a_by_id[cid]
            print(f"\n  [{cid}] {ca.get('question', '')!r}")
            _print_side_by_side(a_by_id.get(cid), b_by_id.get(cid))
        print()

    print(f"Unchanged passing: {len(unchanged_pass) - len(changed)}")
    print()


def _print_side_by_side(ca: dict | None, cb: dict | None) -> None:
    ra = _trunc((ca or {}).get("response") or "(none)", 300)
    rb = _trunc((cb or {}).get("response") or "(none)", 300)

    print(f"    A ({(ca or {}).get('latency_ms', '?')}ms, "
          f"{(ca or {}).get('chunks_retrieved', 0)} chunks): {ra}")
    print(f"    B ({(cb or {}).get('latency_ms', '?')}ms, "
          f"{(cb or {}).get('chunks_retrieved', 0)} chunks): {rb}")

    a_chunks = {ch.get("file") for ch in (ca or {}).get("chunks") or []}
    b_chunks = {ch.get("file") for ch in (cb or {}).get("chunks") or []}
    only_a = a_chunks - b_chunks
    only_b = b_chunks - a_chunks
    if only_a:
        print(f"    <- A-only chunks: {', '.join(sorted(only_a))}")
    if only_b:
        print(f"    -> B-only chunks: {', '.join(sorted(only_b))}")


# ── list runs ─────────────────────────────────────────────────────────────────


def list_runs() -> None:
    files = sorted(LOGS_DIR.glob("golden_results_*.json"), key=lambda p: p.stat().st_mtime)
    if not files:
        print("No golden result files found in logs/")
        return

    print()
    print(f"{'FILE':<45}  {'RUN AT':<27}  {'SCORE':>7}  MODEL")
    print("-" * 110)
    for p in files:
        try:
            d = _load(p)
            cases = d.get("cases", [])
            passed = sum(1 for c in cases if c.get("passed"))
            total = len(cases)
            score = f"{passed}/{total}"
            model = f"{d.get('provider','?')}/{d.get('model','?')}"
            label = f"[{d['label']}] " if d.get("label") else ""
            print(f"{p.name:<45}  {d.get('run_at','?'):<27}  {score:>7}  {label}{model}")
        except Exception as exc:
            print(f"{p.name:<45}  (unreadable: {exc})")
    print()


# ── entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    args = sys.argv[1:]

    if "--list" in args:
        list_runs()
        sys.exit(0)

    verbose = "--verbose" in args or "-v" in args
    failures_only = "--failures-only" in args
    file_args = [Path(a) for a in args if not a.startswith("-")]

    if len(file_args) == 0:
        show(DEFAULT_FILE, verbose=verbose, failures_only=failures_only)
    elif len(file_args) == 1:
        show(file_args[0], verbose=verbose, failures_only=failures_only)
    elif len(file_args) == 2:
        diff(file_args[0], file_args[1])
    else:
        print("Usage: show_results.py [file_a [file_b]] [--verbose] [--failures-only] [--list]",
              file=sys.stderr)
        sys.exit(1)
