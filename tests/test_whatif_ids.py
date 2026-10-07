import pytest

from pitwall.whatif.ids import canonical_json, scenario_id
from pitwall.whatif.models import Change, ScenarioSpec


def _spec(**over):
    base = dict(
        season=2025,
        round=1,
        changes=[
            Change(type="pit_lap", driver="lec", lap=18),
            Change(type="no_safety_car"),
        ],
    )
    base.update(over)
    return ScenarioSpec(**base)


def test_id_is_stable_and_order_independent():
    a = _spec()
    b = ScenarioSpec(
        season=2025,
        round=1,
        changes=[Change(type="no_safety_car"), Change(type="pit_lap", driver="LEC", lap=18)],
    )
    assert scenario_id(a) == scenario_id(b)
    assert len(scenario_id(a)) in (13, 14)  # 80 bits in base62


def test_id_changes_with_spec():
    assert scenario_id(_spec()) != scenario_id(_spec(n_runs=20_000))
    assert scenario_id(_spec()) != scenario_id(_spec(model_version="sim-v2"))


def test_branch_lap_defaults_to_earliest_change():
    s = _spec()
    assert s.effective_branch_lap() == 18
    assert '"branch_lap":18' in canonical_json(s)


def test_change_validation():
    with pytest.raises(ValueError):
        Change(type="pit_lap", lap=10)  # no driver
    with pytest.raises(ValueError):
        Change(type="compound", driver="VER", stop=1)  # no compound
