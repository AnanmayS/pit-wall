"""Run the eval set and report grounding rate and parse accuracy.

Usage: uv run python -m pitwall.ai.evals.run [--limit N] [--out results.jsonl] [--effort medium]
Requires ANTHROPIC_API_KEY (or another SDK credential) and ingested data for the referenced races.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

from pitwall.ai.ask import ask
from pitwall.ai.evals.scoring import parse_ok

QUESTIONS = Path(__file__).with_name("questions.jsonl")


def load_questions(limit: int | None = None) -> list[dict]:
    rows = [json.loads(line) for line in QUESTIONS.read_text().splitlines() if line.strip()]
    return rows[:limit] if limit else rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--out", type=str, default="data/eval-results.jsonl")
    ap.add_argument("--effort", type=str, default="medium")
    args = ap.parse_args()
    if not os.environ.get("ANTHROPIC_API_KEY") and not os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        print(
            "ANTHROPIC_API_KEY is not set; the eval needs a Claude API credential.", file=sys.stderr
        )
        sys.exit(2)
    qs = load_questions(args.limit)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    t0 = time.perf_counter()
    with out_path.open("w") as f:
        for i, q in enumerate(qs, 1):
            r = ask(q["question"], effort=args.effort)
            d = r.to_dict() | {"id": q["id"], "category": q.get("category")}
            d["parse_ok"] = parse_ok(
                q.get("expected_tools", []), q.get("expected_args", {}), d["tool_calls"]
            )
            d["grounded_first_try"] = r.grounded and r.rewrites == 0
            rows.append(d)
            f.write(json.dumps(d) + "\n")
            print(
                f"[{i}/{len(qs)}] {q['id']:<22} parse={int(d['parse_ok'])} grounded={int(r.grounded)} "
                f"first_try={int(d['grounded_first_try'])} tools={len(r.tool_calls)} {r.latency_ms:.0f}ms"
            )
    n = len(rows)
    wall = time.perf_counter() - t0
    cmd = f"`uv run python -m pitwall.ai.evals.run --effort {args.effort}`"
    print("\n| Metric | Value | Command |")
    print("|---|---|---|")
    print(f"| Eval questions | {n} | {cmd} |")
    print(
        f"| Grounding rate (first answer passes) | {sum(r['grounded_first_try'] for r in rows) / n:.1%} | |"
    )
    print(f"| Grounding rate (after one rewrite) | {sum(r['grounded'] for r in rows) / n:.1%} | |")
    print(f"| Refused (could not ground) | {sum(r['refused'] for r in rows) / n:.1%} | |")
    print(
        f"| Parse accuracy (expected tools + args called) | {sum(r['parse_ok'] for r in rows) / n:.1%} | |"
    )
    print(
        f"| Mean tool calls / latency | {sum(len(r['tool_calls']) for r in rows) / n:.1f} / {sum(r['latency_ms'] for r in rows) / n / 1000:.1f} s | |"
    )
    print(
        f"| Tokens in / out (total) | {sum(r['input_tokens'] for r in rows):,} / {sum(r['output_tokens'] for r in rows):,} | |"
    )
    print(f"| Wall time | {wall / 60:.1f} min | |")


if __name__ == "__main__":
    main()
