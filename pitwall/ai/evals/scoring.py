"""Scoring for the eval set: parse accuracy (expected tools + args were called) and grounding."""

from __future__ import annotations

from typing import Any


def _norm(v: Any) -> Any:
    return v.upper() if isinstance(v, str) else v


def _subset(expected: dict, actual: dict) -> bool:
    for k, v in expected.items():
        if k == "changes":
            got = actual.get("changes") or []
            for exp_change in v:
                if not any(_subset(exp_change, g) for g in got):
                    return False
            continue
        if _norm(actual.get(k)) != _norm(v):
            return False
    return True


def parse_ok(
    expected_tools: list[str], expected_args: dict[str, dict], tool_calls: list[dict]
) -> bool:
    """True when every expected tool was called at least once with the expected args as a subset."""
    for name in expected_tools:
        calls = [c for c in tool_calls if c["name"] == name]
        if not calls:
            return False
        exp = expected_args.get(name, {})
        if exp and not any(_subset(exp, c["input"]) for c in calls):
            return False
    return True
