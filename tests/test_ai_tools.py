import json

from pitwall.ai.evals.scoring import parse_ok
from pitwall.ai.tools import TOOLS


def test_tool_schemas_are_strict():
    for t in TOOLS:
        api = t.to_api()
        assert api["strict"] is True
        schema = api["input_schema"]
        assert schema["additionalProperties"] is False
        assert set(schema["required"]) == set(schema["properties"])
        json.dumps(schema)  # serializable


def test_parse_ok_subset_matching():
    calls = [
        {
            "name": "compare_laps",
            "input": {
                "season": 2025,
                "round": 1,
                "session_type": "Q",
                "driver_a": "ver",
                "driver_b": "NOR",
                "lap_a": None,
                "lap_b": None,
            },
        }
    ]
    assert parse_ok(
        ["compare_laps"], {"compare_laps": {"driver_a": "VER", "session_type": "Q"}}, calls
    )
    assert not parse_ok(["compare_laps"], {"compare_laps": {"driver_a": "LEC"}}, calls)
    assert not parse_ok(["get_gaps"], {}, calls)
    wi = [
        {
            "name": "simulate_scenario",
            "input": {
                "season": 2025,
                "round": 2,
                "changes": [
                    {"type": "pit_lap", "driver": "NOR", "lap": 20, "stop": None, "compound": None}
                ],
                "branch_lap": None,
                "n_runs": 10000,
            },
        }
    ]
    assert parse_ok(
        ["simulate_scenario"],
        {"simulate_scenario": {"changes": [{"type": "pit_lap", "driver": "NOR", "lap": 20}]}},
        wi,
    )
    assert not parse_ok(
        ["simulate_scenario"],
        {"simulate_scenario": {"changes": [{"type": "pit_lap", "driver": "NOR", "lap": 21}]}},
        wi,
    )


def test_eval_questions_load():
    from pitwall.ai.evals.run import load_questions

    qs = load_questions()
    assert len(qs) >= 50
    assert all({"id", "question", "expected_tools"} <= set(q) for q in qs)
