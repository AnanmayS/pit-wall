"""Question -> tool calls -> grounded answer.

A manual tool-use loop is used (rather than the SDK tool runner) because the grounding check needs
every tool result and tool input captured, and a failed check must trigger one rewrite before the
answer is refused. Model: settings.claude_model (claude-opus-5-5 by default).
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any

import orjson

from pitwall.ai.grounding import GroundingReport, check_grounding
from pitwall.ai.tools import TOOLS, execute
from pitwall.config import get_settings

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are the analyst on the Pit Wall, an F1 telemetry and simulation platform.
Answer questions about races using ONLY the tools provided. Rules:
- Every number in your answer (times, gaps, metres, km/h, percentages, lap numbers, positions) must come
  from a tool result. Never estimate, extrapolate or compute new numbers; quote the tool's values.
- If the tools cannot answer, say what is missing instead of guessing.
- Driver codes are 3 letters (VER, NOR, LEC ...). Use the current season (2025) if the question gives none.
- Refer to races by their name ("the Chinese Grand Prix"), never by round number; list_sessions maps
  round numbers to names if you need it.
- For "what if" questions, translate the plain-English change into simulate_scenario changes, run it once,
  then report the changed driver's actual result vs the counterfactual probabilities.
- Be concise: lead with the answer, then at most a few supporting facts."""

REWRITE_PROMPT = (
    "Your previous answer contains numbers that do not appear in any tool result: {bad}. "
    "Rewrite the answer using only numbers that appear verbatim in the tool results (rounding is fine), "
    "or state that the value could not be verified. Do not call more tools unless needed."
)
REFUSAL_TEXT = (
    "I can't give a verified answer: the following values do not appear in any tool result: {bad}."
)


@dataclass
class ToolCall:
    name: str
    input: dict
    result: Any
    is_error: bool
    ms: float


@dataclass
class AskResult:
    question: str
    answer: str
    grounded: bool
    refused: bool
    grounding: GroundingReport | None
    tool_calls: list[ToolCall] = field(default_factory=list)
    rewrites: int = 0
    turns: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: float = 0.0
    stop_reason: str = ""
    model: str = ""

    def to_dict(self) -> dict:
        return {
            "question": self.question,
            "answer": self.answer,
            "grounded": self.grounded,
            "refused": self.refused,
            "unmatched": self.grounding.unmatched if self.grounding else [],
            "tool_calls": [
                {"name": t.name, "input": t.input, "is_error": t.is_error, "ms": t.ms}
                for t in self.tool_calls
            ],
            "rewrites": self.rewrites,
            "turns": self.turns,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "latency_ms": self.latency_ms,
            "stop_reason": self.stop_reason,
            "model": self.model,
        }


def _dumps(obj: Any) -> str:
    return orjson.dumps(obj, default=str).decode()


def _text_of(content) -> str:
    return "\n".join(b.text for b in content if getattr(b, "type", "") == "text").strip()


def ask(
    question: str,
    *,
    client=None,
    model: str | None = None,
    effort: str = "medium",
    max_turns: int = 8,
    max_rewrites: int = 1,
) -> AskResult:
    import anthropic

    settings = get_settings()
    model = model or settings.claude_model
    client = client or anthropic.Anthropic()
    tools = [t.to_api() for t in TOOLS]
    messages: list[dict] = [{"role": "user", "content": question}]
    res = AskResult(
        question=question, answer="", grounded=False, refused=False, grounding=None, model=model
    )
    tool_results_seen: list[Any] = []
    tool_inputs_seen: list[Any] = []
    t_start = time.perf_counter()

    while res.turns < max_turns:
        res.turns += 1
        response = client.messages.create(
            model=model,
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            tools=tools,
            messages=messages,
            output_config={"effort": effort},
        )
        res.input_tokens += response.usage.input_tokens
        res.output_tokens += response.usage.output_tokens
        res.stop_reason = response.stop_reason or ""
        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason == "tool_use":
            results_block = []
            for block in response.content:
                if block.type != "tool_use":
                    continue
                inputs = block.input if isinstance(block.input, dict) else json.loads(block.input)
                t0 = time.perf_counter()
                result, is_error = execute(block.name, inputs)
                ms = (time.perf_counter() - t0) * 1000
                res.tool_calls.append(ToolCall(block.name, inputs, result, is_error, ms))
                tool_inputs_seen.append(inputs)
                if not is_error:
                    tool_results_seen.append(result)
                results_block.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": _dumps(result),
                        "is_error": is_error,
                    }
                )
            messages.append({"role": "user", "content": results_block})
            continue

        if response.stop_reason == "refusal":
            res.answer = "The model declined to answer this question."
            res.refused = True
            break

        answer = _text_of(response.content)
        report = check_grounding(answer, tool_results_seen, question, tool_inputs_seen)
        res.answer, res.grounding = answer, report
        if report.ok:
            res.grounded = True
            break
        if res.rewrites < max_rewrites:
            res.rewrites += 1
            messages.append(
                {"role": "user", "content": REWRITE_PROMPT.format(bad=", ".join(report.unmatched))}
            )
            continue
        res.answer = REFUSAL_TEXT.format(bad=", ".join(report.unmatched))
        res.refused = True
        break

    res.latency_ms = (time.perf_counter() - t_start) * 1000
    return res
