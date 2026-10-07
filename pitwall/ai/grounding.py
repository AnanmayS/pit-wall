"""Programmatic grounding check: every number in an answer must appear in a tool result.

The allowed set is built from every tool result (walked recursively) plus the user's question and
the tool-call inputs, expanded with the variants a sensible answer might use:
rounded to 0-3 decimals, milliseconds expressed as seconds, probabilities as percentages, and lap
times as m:ss.mmm strings. The check is set membership with a small relative tolerance, so a judge
model is never asked whether a number "looks right".
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any

# numbers like 0.12, 1:20.456, 12%, -3.5, 1,234 ; ignores years inside words/ids
_NUM_RE = re.compile(
    r"(?<![A-Za-z0-9_])(\d{1,2}:\d{2}\.\d{1,3}|\d{1,2}:\d{2}|-?\d[\d,]*\.?\d*)(?![A-Za-z0-9_])"
)
_ORDINAL_RE = re.compile(r"\b(P|T)(\d{1,2})\b")  # P3, T1 are positions/corners, not quantities


@dataclass
class GroundingReport:
    ok: bool
    answer_numbers: list[str]
    unmatched: list[str]
    allowed_count: int
    notes: list[str] = field(default_factory=list)


def _lap_time_strings(ms: float) -> set[str]:
    if ms <= 0 or ms > 10 * 60 * 1000:
        return set()
    total_s = ms / 1000.0
    m, s = divmod(total_s, 60)
    out = {f"{int(m)}:{s:06.3f}", f"{int(m)}:{s:05.2f}", f"{int(m)}:{s:04.1f}"}
    return out


def _variants(x: float) -> set[float]:
    out: set[float] = set()
    if not math.isfinite(x):
        return out
    for nd in (0, 1, 2, 3):
        out.add(round(x, nd))
    out.add(x)
    # ms -> s and s -> ms
    for nd in (0, 1, 2, 3):
        out.add(round(x / 1000.0, nd))
    out.add(round(x * 1000.0, 0))
    # probability -> percent
    if 0.0 <= x <= 1.0:
        for nd in (0, 1, 2):
            out.add(round(x * 100.0, nd))
    out.add(abs(x))
    return out


def _walk(obj: Any, nums: set[float], strings: set[str]) -> None:
    if isinstance(obj, bool):
        return
    if isinstance(obj, int | float):
        nums.update(_variants(float(obj)))
        if isinstance(obj, int | float) and float(obj) > 1000:
            strings.update(_lap_time_strings(float(obj)))
        return
    if isinstance(obj, str):
        for tok in _NUM_RE.findall(obj):
            parsed = parse_number(tok)
            if parsed is not None:
                nums.update(_variants(parsed))
            if ":" in tok:
                strings.add(tok)
        return
    if isinstance(obj, dict):
        for v in obj.values():
            _walk(v, nums, strings)
        return
    if isinstance(obj, list | tuple):
        for v in obj:
            _walk(v, nums, strings)


def parse_number(tok: str) -> float | None:
    tok = tok.strip().rstrip(".")
    if ":" in tok:
        m, s = tok.split(":", 1)
        try:
            return int(m) * 60_000 + float(s) * 1000  # ms
        except ValueError:
            return None
    try:
        return float(tok.replace(",", ""))
    except ValueError:
        return None


def allowed_numbers(
    tool_results: list[Any], question: str = "", tool_inputs: list[Any] | None = None
) -> tuple[set[float], set[str]]:
    nums: set[float] = set()
    strings: set[str] = set()
    for r in tool_results:
        _walk(r, nums, strings)
    _walk(question, nums, strings)
    for inp in tool_inputs or []:
        _walk(inp, nums, strings)
    return nums, strings


def extract_answer_numbers(answer: str) -> list[str]:
    cleaned = _ORDINAL_RE.sub(" ", answer)
    return [t for t in _NUM_RE.findall(cleaned) if t not in ("",)]


def _matches(
    value: float, allowed: set[float], rel_tol: float = 1e-3, abs_tol: float = 5e-4
) -> bool:
    for a in allowed:
        if math.isclose(value, a, rel_tol=rel_tol, abs_tol=abs_tol):
            return True
    return False


def check_grounding(
    answer: str, tool_results: list[Any], question: str = "", tool_inputs: list[Any] | None = None
) -> GroundingReport:
    nums, strings = allowed_numbers(tool_results, question, tool_inputs)
    tokens = extract_answer_numbers(answer)
    unmatched: list[str] = []
    for tok in tokens:
        if ":" in tok:
            if tok in strings or (
                parse_number(tok) is not None and _matches(parse_number(tok), nums)
            ):
                continue
            unmatched.append(tok)
            continue
        val = parse_number(tok)
        if val is None:
            continue
        if _matches(val, nums):
            continue
        # small integers used as counts/ordinals ("two drivers", "3 corners") are tolerated up to 20
        if val.is_integer() and 0 <= val <= 20:
            continue
        unmatched.append(tok)
    return GroundingReport(
        ok=not unmatched,
        answer_numbers=tokens,
        unmatched=unmatched,
        allowed_count=len(nums),
    )
