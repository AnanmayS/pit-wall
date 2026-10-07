import pytest

from pitwall.db.dynamo import create_table
from pitwall.whatif.models import Change, ScenarioSpec
from pitwall.whatif.store import get_scenario, list_recent, put_result, put_scenario

pytestmark = pytest.mark.integration


def test_scenario_roundtrip_and_cache_hit():
    create_table()
    spec = ScenarioSpec(season=1999, round=99, changes=[Change(type="dnf", driver="XXX", lap=5)])
    sid = put_scenario(spec)
    assert put_scenario(spec) == sid  # idempotent
    miss = get_scenario(sid, spec.model_version)
    assert miss is not None and miss.cache_hit is False and miss.views == 1
    put_result(sid, spec.model_version, {"summary": [{"driver": "XXX", "p_win": 0.1}]}, 12.3)
    hit = get_scenario(sid, spec.model_version)
    assert hit.cache_hit and hit.result["summary"][0]["p_win"] == 0.1 and hit.views == 2
    recent = list_recent(1999, 99)
    assert any(r["id"] == sid for r in recent)
