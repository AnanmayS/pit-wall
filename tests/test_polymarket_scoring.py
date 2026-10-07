"""Scoring functions: implied probabilities, multi-outcome Brier, log-loss, per-race comparison."""

from __future__ import annotations

import math

import pytest

from pitwall.odds.scoring import brier, implied_probs, log_loss, score_race


def test_implied_probs_normalizes_and_keeps_raw():
    out = implied_probs({"VER": 0.5, "NOR": 0.3, "PIA": 0.3})
    assert out["total"] == pytest.approx(1.1)
    assert out["raw"] == {"VER": 0.5, "NOR": 0.3, "PIA": 0.3}
    assert sum(out["probs"].values()) == pytest.approx(1.0)
    assert out["probs"]["VER"] == pytest.approx(0.5 / 1.1)
    assert out["n"] == 3


def test_implied_probs_drops_missing_and_clips_negative():
    out = implied_probs({"VER": 0.6, "NOR": None, "PIA": float("nan"), "LEC": -0.1, "HAM": 0.2})
    assert set(out["probs"]) == {"VER", "LEC", "HAM"}
    assert out["probs"]["LEC"] == 0.0
    assert out["probs"]["VER"] == pytest.approx(0.75)


def test_implied_probs_rejects_all_zero():
    with pytest.raises(ValueError):
        implied_probs({"VER": 0.0, "NOR": None})


def test_brier_perfect_and_worst():
    assert brier({"VER": 1.0, "NOR": 0.0}, "VER") == 0.0
    assert brier({"VER": 1.0, "NOR": 0.0}, "NOR") == pytest.approx(2.0)


def test_brier_multi_outcome_value():
    # (0.5-1)^2 + 0.3^2 + 0.2^2 = 0.25 + 0.09 + 0.04
    assert brier({"VER": 0.5, "NOR": 0.3, "PIA": 0.2}, "VER") == pytest.approx(0.38)


def test_brier_winner_not_in_forecast_counts_as_zero_probability():
    # y=1 for the missing winner: (0 - 1)^2 = 1 on top of the listed drivers' squared mass
    assert brier({"VER": 0.6, "NOR": 0.4}, "ALO") == pytest.approx(0.36 + 0.16 + 1.0)


def test_brier_uniform_over_n():
    n = 20
    probs = {f"D{i}": 1 / n for i in range(n)}
    assert brier(probs, "D0") == pytest.approx(1 - 1 / n)


def test_log_loss():
    assert log_loss({"VER": 0.5, "NOR": 0.5}, "VER") == pytest.approx(math.log(2))
    assert log_loss({"VER": 1.0}, "VER") == 0.0
    assert log_loss({"VER": 1.0}, "NOR", eps=1e-6) == pytest.approx(-math.log(1e-6))


def test_score_race_compares_both_forecasts():
    ours = {"VER": 0.6, "NOR": 0.3, "PIA": 0.1}
    market_prices = {"VER": 0.45, "NOR": 0.45, "PIA": 0.2}  # sums to 1.1, normalized inside
    res = score_race(ours, market_prices, "VER")
    m = {k: v / 1.1 for k, v in market_prices.items()}
    assert res["winner"] == "VER"
    assert res["our"]["brier"] == pytest.approx(brier(ours, "VER"))
    assert res["market"]["brier"] == pytest.approx(brier(m, "VER"))
    assert res["market"]["p_winner"] == pytest.approx(0.45 / 1.1)
    assert res["our"]["log_loss"] == pytest.approx(-math.log(0.6))
    assert res["brier_diff"] < 0  # we put more on the winner
    assert res["log_loss_diff"] == pytest.approx(-math.log(0.6) + math.log(0.45 / 1.1))


def test_score_race_without_normalization():
    res = score_race({"A": 1.0}, {"A": 0.5, "B": 0.5}, "A", normalize_market=False)
    assert res["market"]["brier"] == pytest.approx(0.5)
