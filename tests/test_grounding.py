from pitwall.ai.grounding import check_grounding, extract_answer_numbers


def test_numbers_from_tool_results_pass():
    tools = [
        {
            "total_delta_ms": 123.4,
            "corners": [{"name": "T1", "brake_delta_m": 8.2, "delta_ms": 118}],
        }
    ]
    rep = check_grounding("VER brakes 8 m later into T1, worth 0.12 s (0.123 s total).", tools)
    assert rep.ok, rep.unmatched


def test_invented_number_fails():
    tools = [{"total_delta_ms": 123.4}]
    rep = check_grounding("VER was 0.45 s faster.", tools)
    assert not rep.ok and rep.unmatched == ["0.45"]


def test_probabilities_as_percent():
    rep = check_grounding("Leclerc wins 31% of runs.", [{"p_win": 0.3104}])
    assert rep.ok


def test_lap_time_strings_and_ms():
    rep = check_grounding("His fastest lap was 1:20.456.", [{"lap_time_ms": 80456}])
    assert rep.ok
    rep = check_grounding("His fastest lap was 1:21.000.", [{"lap_time_ms": 80456}])
    assert not rep.ok


def test_question_numbers_are_allowed():
    rep = check_grounding(
        "On lap 18 of the 2025 race, nothing changed.",
        [],
        question="What if Leclerc pits on lap 18 in 2025?",
    )
    assert rep.ok


def test_extract_ignores_positions_and_corner_labels():
    assert extract_answer_numbers("P3 at T14 after 0.5 s") == ["0.5"]
