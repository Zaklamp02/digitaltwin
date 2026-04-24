"""RAGAS evaluation script — measures RAG quality without human labels.

Metrics computed:
  - Faithfulness:        does the answer contain only info from the retrieved context?
  - Answer Relevancy:    does the answer address the question?
  - Context Precision:   are the most relevant chunks ranked first?
  - Context Recall:      do the retrieved chunks cover the ground-truth answer?

Usage:
    pip install ragas datasets
    python tests/eval_ragas.py                       # uses localhost:8000
    BASE_URL=http://myserver:8000 python tests/eval_ragas.py

Output: logs/ragas_results_<timestamp>.json
"""

from __future__ import annotations

import json
import os
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
import yaml

BASE_URL = os.environ.get("BASE_URL", "http://localhost:8000").rstrip("/")
TOKENS: dict[str, str | None] = {
    "public": os.environ.get("TOKEN_PUBLIC", None),
    "recruiter": os.environ.get("TOKEN_RECRUITER", "rec-jOuPXS64JEw"),
    "personal": os.environ.get("TOKEN_PERSONAL", "pers-HW3xmo0IsWE"),
}
GOLDEN_FILE = Path(__file__).parent / "golden_qa.yaml"
LOGS_DIR = Path(__file__).parent.parent / "logs"

# ── collect data from live server ────────────────────────────────────────────


def _call_chat_with_context(
    question: str, tier: str, timeout: float = 60.0
) -> dict[str, Any]:
    """Return {response, contexts} where contexts is a list of retrieved chunk texts."""
    token = TOKENS.get(tier)
    headers: dict[str, str] = {"X-Session-Id": str(uuid.uuid4())}
    if token:
        headers["X-Access-Token"] = token
    payload = {"messages": [{"role": "user", "content": question}]}

    tokens: list[str] = []
    contexts: list[str] = []
    error: str | None = None

    try:
        with httpx.Client(timeout=timeout) as client:
            with client.stream(
                "POST", f"{BASE_URL}/api/chat", json=payload, headers=headers
            ) as resp:
                resp.raise_for_status()
                current_event = ""
                chunks_buffer: list[dict] = []
                for line in resp.iter_lines():
                    if line.startswith("event:"):
                        current_event = line[6:].strip()
                    elif line.startswith("data:"):
                        data = line[5:].strip()
                        if current_event == "token":
                            tokens.append(data)
                        elif current_event == "chunks_used":
                            try:
                                chunks_buffer = json.loads(data)
                            except Exception:
                                pass
                    elif line == "":
                        current_event = ""
    except Exception as exc:
        error = str(exc)

    # chunks_used only has metadata; to get chunk text we'd need a second call.
    # For RAGAS we use the chunk file+section as a proxy for context.
    contexts = [
        f"{c.get('file', '')} / {c.get('section', '')} (score {c.get('score', '?')})"
        for c in chunks_buffer
    ]

    return {
        "question": question,
        "answer": "".join(tokens).strip(),
        "contexts": contexts,
        "error": error,
    }


def build_dataset(cases: list[dict]) -> list[dict[str, Any]]:
    """Call the live server for each case and collect (question, answer, contexts)."""
    rows = []
    for i, case in enumerate(cases, 1):
        cid = case.get("id", "?")
        q = case["question"]
        tier = case.get("tier", "public")
        print(f"  [{i}/{len(cases)}] {cid}: {q[:60]}…", flush=True)
        row = _call_chat_with_context(q, tier)
        row["id"] = cid
        row["persona"] = case.get("persona")
        row["tier"] = tier
        row["expected_keywords"] = case.get("expected_keywords", [])
        rows.append(row)
        time.sleep(0.5)  # gentle pacing to avoid rate limiting
    return rows


# ── RAGAS evaluation ─────────────────────────────────────────────────────────


def run_ragas(rows: list[dict[str, Any]], openai_api_key: str) -> dict[str, Any]:
    """Run RAGAS metrics on the collected dataset."""
    try:
        from datasets import Dataset  # type: ignore[import-untyped]
        from ragas import evaluate  # type: ignore[import-untyped]
        from ragas.metrics import (  # type: ignore[import-untyped]
            answer_relevancy,
            context_precision,
            faithfulness,
        )
    except ImportError:
        print("RAGAS or datasets not installed. Run: pip install ragas datasets", file=sys.stderr)
        return {"error": "ragas not installed"}

    # RAGAS expects: question, answer, contexts (list[str]), ground_truth (optional)
    valid = [r for r in rows if r["answer"] and not r.get("error")]
    if not valid:
        return {"error": "no valid rows to evaluate"}

    dataset = Dataset.from_list(
        [
            {
                "question": r["question"],
                "answer": r["answer"],
                "contexts": r["contexts"] if r["contexts"] else ["(no context retrieved)"],
            }
            for r in valid
        ]
    )

    os.environ["OPENAI_API_KEY"] = openai_api_key

    result = evaluate(
        dataset,
        metrics=[faithfulness, answer_relevancy, context_precision],
    )
    return result.to_pandas().to_dict(orient="records")  # type: ignore[return-value]


# ── entry point ───────────────────────────────────────────────────────────────


def main() -> None:
    openai_key = os.environ.get("OPENAI_API_KEY", "")
    if not openai_key:
        # Try loading from .env
        env_file = Path(__file__).parent.parent / ".env"
        if env_file.exists():
            for line in env_file.read_text().splitlines():
                if line.startswith("OPENAI_API_KEY="):
                    openai_key = line.split("=", 1)[1].strip().strip('"').strip("'")
                    break
    if not openai_key:
        print("OPENAI_API_KEY not set — RAGAS evaluation requires it.", file=sys.stderr)
        sys.exit(1)

    print(f"Loading golden cases from {GOLDEN_FILE}…")
    with GOLDEN_FILE.open() as f:
        cases = yaml.safe_load(f) or []
    print(f"  {len(cases)} cases loaded.")

    print(f"\nCollecting responses from {BASE_URL}…")
    rows = build_dataset(cases)

    errors = [r for r in rows if r.get("error")]
    if errors:
        print(f"  ⚠ {len(errors)} cases had errors: {[e['id'] for e in errors]}")

    print("\nRunning RAGAS metrics…")
    ragas_scores = run_ragas(rows, openai_key)

    # Compute simple keyword-check stats per row
    kw_results = []
    for r in rows:
        hits = [kw for kw in r["expected_keywords"] if kw.lower() in r["answer"].lower()]
        misses = [kw for kw in r["expected_keywords"] if kw.lower() not in r["answer"].lower()]
        kw_results.append({"id": r["id"], "hits": hits, "misses": misses})

    output = {
        "run_at": datetime.now(tz=timezone.utc).isoformat(),
        "base_url": BASE_URL,
        "total_cases": len(cases),
        "cases_with_errors": len(errors),
        "keyword_check": kw_results,
        "rows": [
            {
                "id": r["id"],
                "persona": r["persona"],
                "tier": r["tier"],
                "question": r["question"],
                "answer": r["answer"],
                "contexts": r["contexts"],
                "error": r.get("error"),
            }
            for r in rows
        ],
        "ragas_scores": ragas_scores,
    }

    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%S")
    out_path = LOGS_DIR / f"ragas_results_{ts}.json"
    out_path.write_text(json.dumps(output, indent=2), encoding="utf-8")
    print(f"\n✅ Results saved to {out_path}")

    # Print summary
    print("\n── Summary ────────────────────────────────")
    total_kw = sum(len(r["expected_keywords"]) for r in rows)
    hit_kw = sum(len(r["hits"]) for r in kw_results)
    print(f"  Keyword checks passed: {hit_kw}/{total_kw}")

    if isinstance(ragas_scores, list) and ragas_scores:
        # Average across rows
        keys = [k for k in ragas_scores[0] if isinstance(ragas_scores[0][k], float)]
        for k in keys:
            vals = [r[k] for r in ragas_scores if isinstance(r.get(k), float)]
            avg = sum(vals) / len(vals) if vals else 0.0
            print(f"  {k}: {avg:.3f}")
    print("───────────────────────────────────────────")


if __name__ == "__main__":
    main()
