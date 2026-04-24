"""Golden Q&A test harness.

Runs against a live server (default: http://localhost:8000).
Each test case in golden_qa.yaml is sent through /api/chat as a single-turn
conversation, the full response is collected from the SSE stream, then
expected_keywords and forbidden_phrases are checked.

Usage:
    pytest tests/test_golden.py -v                      # against localhost:8000
    BASE_URL=http://myserver:8000 pytest tests/test_golden.py -v

Results are written to logs/golden_results_latest.json for later inspection
or import into the admin dashboard.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
import pytest
import yaml

# ── config ────────────────────────────────────────────────────────────────────

BASE_URL = os.environ.get("BASE_URL", "http://localhost:5173").rstrip("/")

# Tokens — defaults match the dev credentials.yaml; override via env vars.
TOKENS: dict[str, str | None] = {
    "public": os.environ.get("TOKEN_PUBLIC", None),
    "recruiter": os.environ.get("TOKEN_RECRUITER", "rec-jOuPXS64JEw"),
    "personal": os.environ.get("TOKEN_PERSONAL", "pers-HW3xmo0IsWE"),
}

GOLDEN_FILE = Path(__file__).parent / "golden_qa.yaml"
LOGS_DIR = Path(__file__).parent.parent / "logs"

# Optional run label — tag a run so you can compare later:
#   LABEL=gpt-4o make test-golden
# Result saved to logs/golden_results_<label>.json AND logs/golden_results_latest.json.
LABEL: str | None = os.environ.get("LABEL")
RESULTS_FILE = LOGS_DIR / (f"golden_results_{LABEL}.json" if LABEL else "golden_results_latest.json")

# ── SSE helper ────────────────────────────────────────────────────────────────


def _call_chat(
    question: str,
    tier: str,
    timeout: float = 60.0,
    fake_ip: str | None = None,
) -> dict[str, Any]:
    """POST to /api/chat synchronously via httpx, collect the full SSE stream.

    ``fake_ip`` is injected as the first ``X-Forwarded-For`` value so that each
    test case gets its own rate-limit bucket (the backend reads XFF[0]).

    Returns:
        {
            "response": <full assistant text>,
            "chunks": [...],
            "latency_ms": int,
            "error": str | None,
        }
    """
    token = TOKENS.get(tier)
    headers: dict[str, str] = {"X-Session-Id": str(uuid.uuid4())}
    if token:
        headers["X-Access-Token"] = token
    if fake_ip:
        # Prepend a fake IP so the app's xff.split(",")[0] yields a unique
        # rate-limit bucket per test, avoiding per-IP daily cap exhaustion.
        headers["X-Forwarded-For"] = fake_ip

    payload = {"messages": [{"role": "user", "content": question}]}

    tokens: list[str] = []
    chunks_meta: list[dict] = []
    error: str | None = None
    t0 = time.monotonic()

    try:
        with httpx.Client(timeout=timeout) as client:
            with client.stream(
                "POST",
                f"{BASE_URL}/api/chat",
                json=payload,
                headers=headers,
            ) as resp:
                resp.raise_for_status()
                current_event = ""
                for line in resp.iter_lines():
                    if line.startswith("event:"):
                        current_event = line[6:].strip()
                    elif line.startswith("data:"):
                        # Per SSE spec: strip at most one leading space after 'data:'
                        raw = line[5:]
                        data = raw[1:] if raw.startswith(" ") else raw
                        if current_event == "token":
                            tokens.append(data)
                        elif current_event == "chunks_used":
                            try:
                                chunks_meta = json.loads(data)
                            except Exception:
                                pass
                        elif current_event == "error":
                            try:
                                error = json.loads(data).get("message", data)
                            except Exception:
                                error = data
                    elif line == "":
                        current_event = ""
    except Exception as exc:
        error = str(exc)

    latency_ms = int((time.monotonic() - t0) * 1000)
    return {
        "response": "".join(tokens).strip(),
        "chunks": chunks_meta,
        "latency_ms": latency_ms,
        "error": error,
    }


# ── load test cases ───────────────────────────────────────────────────────────


def _load_cases() -> list[dict]:
    with GOLDEN_FILE.open() as f:
        return yaml.safe_load(f) or []


# ── parametrised test ─────────────────────────────────────────────────────────


def pytest_configure(config):
    """Register custom marker so -m persona=recruiter etc work."""
    config.addinivalue_line("markers", "persona: test persona (recruiter/colleague/regression)")


def _case_id(case: dict) -> str:
    return case.get("id", case.get("question", "?")[:40])


def _fetch_server_meta() -> dict:
    """Call /api/health and return model/provider info for the envelope."""
    try:
        r = httpx.get(f"{BASE_URL}/api/health", timeout=10)
        r.raise_for_status()
        data = r.json()
        return {
            "provider": data.get("provider"),
            "model": data.get("model"),
            "embedding_provider": data.get("embedding_provider"),
            "version": data.get("version"),
        }
    except Exception as exc:
        return {"server_meta_error": str(exc)}


@pytest.fixture(scope="session")
def golden_results() -> dict:
    """Session-scoped accumulator for result output."""
    meta = _fetch_server_meta()
    return {
        "run_at": datetime.now(tz=timezone.utc).isoformat(),
        "label": LABEL,
        "base_url": BASE_URL,
        **meta,
        "cases": [],
    }


@pytest.fixture(scope="session", autouse=True)
def _write_results(golden_results):
    """Write results — to RESULTS_FILE and always to latest."""
    yield
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(golden_results, indent=2)
    RESULTS_FILE.write_text(payload, encoding="utf-8")
    # Always keep a copy at latest for quick access
    latest = LOGS_DIR / "golden_results_latest.json"
    if RESULTS_FILE != latest:
        latest.write_text(payload, encoding="utf-8")
    print(f"\n✅ Results written to {RESULTS_FILE}")


@pytest.mark.parametrize("case", _load_cases(), ids=_case_id)
def test_golden(case: dict, golden_results: dict) -> None:
    question = case["question"]
    tier = case.get("tier", "public")
    expected = [kw.lower() for kw in case.get("expected_keywords", [])]
    forbidden = [fp.lower() for fp in case.get("forbidden_phrases", [])]

    # Give each case a unique fake source IP so public-tier tests don't share
    # the same daily rate-limit bucket and exhaust it mid-run.
    fake_ip = f"192.0.2.{(abs(hash(case.get('id', question))) % 253) + 1}"
    result = _call_chat(question, tier, fake_ip=fake_ip)
    response_lower = result["response"].lower()

    # Record result regardless of pass/fail
    case_result: dict[str, Any] = {
        "id": case.get("id"),
        "persona": case.get("persona"),
        "tier": tier,
        "question": question,
        "response": result["response"],
        "latency_ms": result["latency_ms"],
        # Store full chunk metadata so runs can be compared chunk-by-chunk.
        "chunks": result["chunks"],
        "chunks_retrieved": len(result["chunks"]),
        "error": result["error"],
        "keyword_hits": [],
        "keyword_misses": [],
        "forbidden_hits": [],
        "passed": True,
    }

    failures: list[str] = []

    if result["error"]:
        failures.append(f"API error: {result['error']}")
        case_result["passed"] = False

    for kw in expected:
        if kw in response_lower:
            case_result["keyword_hits"].append(kw)
        else:
            case_result["keyword_misses"].append(kw)
            failures.append(f"Missing expected keyword: '{kw}'")

    for fp in forbidden:
        if fp in response_lower:
            case_result["forbidden_hits"].append(fp)
            failures.append(f"Forbidden phrase found: '{fp}'")

    if failures:
        case_result["passed"] = False

    golden_results["cases"].append(case_result)

    if failures:
        pytest.fail(
            f"[{case.get('id')}] {question!r}\n"
            f"Response (first 500 chars): {result['response'][:500]!r}\n"
            + "\n".join(f"  ✗ {f}" for f in failures)
        )
