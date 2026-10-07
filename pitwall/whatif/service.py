"""Run a What If scenario through the DynamoDB cache. Shared by the API and the AI tool."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from pitwall.sim.counterfactual import run_scenario
from pitwall.whatif import store
from pitwall.whatif.ids import scenario_id
from pitwall.whatif.models import ScenarioSpec

log = logging.getLogger(__name__)


@dataclass
class WhatIfResponse:
    id: str
    cache_hit: bool
    views: int
    created_at: str
    result: dict

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "cache_hit": self.cache_hit,
            "views": self.views,
            "created_at": self.created_at,
            "spec": None,
            **self.result,
        }


def run_or_cached(spec: ScenarioSpec, *, use_cache: bool = True) -> WhatIfResponse:
    """Return the cached result for this scenario, computing and storing it on a miss."""
    sid = scenario_id(spec)
    if use_cache:
        store.put_scenario(spec)
        cached = store.get_scenario(sid, spec.model_version)
        if cached is not None and cached.result is not None:
            log.info("whatif %s: cache hit (views=%d)", sid, cached.views)
            return WhatIfResponse(sid, True, cached.views, cached.created_at, cached.result)
    outcome = run_scenario(spec, scenario_id=sid)
    result = outcome.to_dict()
    if use_cache:
        store.put_result(sid, spec.model_version, result, outcome.compute_ms)
        meta = store.get_scenario(sid, spec.model_version, count_view=False)
        return WhatIfResponse(
            sid, False, meta.views if meta else 0, meta.created_at if meta else "", result
        )
    return WhatIfResponse(sid, False, 0, "", result)


def open_shared(sid: str, model_version: str = "sim-v1") -> WhatIfResponse | None:
    """Open a share link: counts a view, recomputes if the cached result expired."""
    cached = store.get_scenario(sid, model_version)
    if cached is None:
        return None
    if cached.result is None:
        outcome = run_scenario(cached.spec, scenario_id=sid)
        result = outcome.to_dict()
        store.put_result(sid, model_version, result, outcome.compute_ms)
        return WhatIfResponse(sid, False, cached.views, cached.created_at, result)
    return WhatIfResponse(sid, True, cached.views, cached.created_at, cached.result)
