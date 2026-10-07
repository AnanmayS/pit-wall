"""Probability scoring for multi-outcome events (one winner among many drivers). Pure functions.

Brier score here is the multi-outcome form: sum over outcomes of (p_i - y_i)^2, range 0 (perfect) to
2 (all mass on a wrong outcome). A driver missing from a forecast has p = 0, so a winner that the
forecast did not list contributes (0 - 1)^2 = 1.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

DEFAULT_EPS = 1e-6


def implied_probs(prices_by_driver: Mapping[str, float | None]) -> dict[str, Any]:
    """Normalize Yes prices across an event's outcomes so they sum to 1.

    Returns {"probs": normalized, "raw": raw prices used, "total": sum of raw prices (the
    overround; >1 means the book is over-priced), "n": outcomes}. Missing/NaN prices are dropped,
    negative prices clipped to 0. Raises ValueError if no positive price remains.
    """
    raw: dict[str, float] = {}
    for k, v in prices_by_driver.items():
        if v is None:
            continue
        x = float(v)
        if math.isnan(x):
            continue
        raw[k] = max(0.0, x)
    total = sum(raw.values())
    if total <= 0:
        raise ValueError("implied_probs needs at least one positive price")
    return {
        "probs": {k: v / total for k, v in raw.items()},
        "raw": raw,
        "total": total,
        "n": len(raw),
    }


def brier(probs: Mapping[str, float], winner: str) -> float:
    """Multi-outcome Brier score: sum over outcomes of (p - y)^2, y = 1 for the winner only."""
    score = sum((float(p) - (1.0 if k == winner else 0.0)) ** 2 for k, p in probs.items())
    if winner not in probs:
        score += 1.0
    return score


def log_loss(probs: Mapping[str, float], winner: str, eps: float = DEFAULT_EPS) -> float:
    """-ln p(winner), with p clipped to [eps, 1] so a zero forecast costs -ln(eps), not infinity."""
    p = float(probs.get(winner, 0.0))
    return -math.log(min(1.0, max(eps, p)))


def score_race(
    our: Mapping[str, float],
    market: Mapping[str, float],
    winner: str,
    *,
    normalize_market: bool = True,
    eps: float = DEFAULT_EPS,
) -> dict[str, Any]:
    """Brier and log-loss of our forecast and of the market for one event.

    `market` holds raw Yes prices when normalize_market is True (the default), else probabilities.
    Our forecast is used as given (it should already sum to ~1).
    """
    m = implied_probs(market)["probs"] if normalize_market else dict(market)
    ours = {k: float(v) for k, v in our.items()}
    res = {
        "winner": winner,
        "our": {
            "brier": brier(ours, winner),
            "log_loss": log_loss(ours, winner, eps),
            "p_winner": ours.get(winner, 0.0),
        },
        "market": {
            "brier": brier(m, winner),
            "log_loss": log_loss(m, winner, eps),
            "p_winner": m.get(winner, 0.0),
        },
    }
    res["brier_diff"] = res["our"]["brier"] - res["market"]["brier"]  # < 0: we beat the market
    res["log_loss_diff"] = res["our"]["log_loss"] - res["market"]["log_loss"]
    return res
