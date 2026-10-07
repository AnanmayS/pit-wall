"""DynamoDB access for What If scenarios (single-table design, PLAN.md section 5)."""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import orjson
from boto3.dynamodb.conditions import Key

from pitwall.db.dynamo import GSI1, get_table
from pitwall.whatif.ids import canonical_json, scenario_digest, scenario_id
from pitwall.whatif.models import ScenarioSpec

RESULT_TTL_SECONDS = 30 * 24 * 3600


@dataclass
class CachedScenario:
    id: str
    spec: ScenarioSpec
    result: dict | None
    views: int
    created_at: str
    cache_hit: bool


def _pk(sid: str) -> str:
    return f"SCEN#{sid}"


def _race_key(spec: ScenarioSpec) -> str:
    return f"RACE#{spec.season}#{spec.round:02d}"


def _dumps(obj: Any) -> str:
    return orjson.dumps(obj).decode()


def _plain(obj: Any) -> Any:
    """Convert DynamoDB Decimals back into ints/floats for JSON responses."""
    if isinstance(obj, Decimal):
        return int(obj) if obj == obj.to_integral_value() else float(obj)
    if isinstance(obj, dict):
        return {k: _plain(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_plain(v) for v in obj]
    return obj


def put_scenario(spec: ScenarioSpec) -> str:
    """Write the META item (idempotent) and return the scenario id."""
    sid = scenario_id(spec)
    table = get_table()
    now = datetime.now(UTC).isoformat(timespec="seconds")
    table.put_item(
        Item={
            "PK": _pk(sid),
            "SK": "META",
            "id": sid,
            "digest": scenario_digest(spec),
            "spec": canonical_json(spec),
            "season": spec.season,
            "round": spec.round,
            "model_version": spec.model_version,
            "created_at": now,
            "GSI1PK": _race_key(spec),
            "GSI1SK": f"{now}#{sid}",
        },
        ConditionExpression="attribute_not_exists(PK)",
    ) if not _exists(table, sid) else None
    return sid


def _exists(table, sid: str) -> bool:
    return "Item" in table.get_item(Key={"PK": _pk(sid), "SK": "META"}, ProjectionExpression="PK")


def put_result(sid: str, model_version: str, result: dict, compute_ms: float) -> None:
    table = get_table()
    table.put_item(
        Item={
            "PK": _pk(sid),
            "SK": f"RESULT#{model_version}",
            "result": _dumps(result),
            "compute_ms": Decimal(str(round(compute_ms, 1))),
            "computed_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "ttl": int(time.time()) + RESULT_TTL_SECONDS,
        }
    )


def get_scenario(sid: str, model_version: str, *, count_view: bool = True) -> CachedScenario | None:
    """One Query on PK returns META + RESULT + STATS. Returns None if the scenario is unknown."""
    table = get_table()
    items = table.query(KeyConditionExpression=Key("PK").eq(_pk(sid)))["Items"]
    by_sk = {it["SK"]: it for it in items}
    meta = by_sk.get("META")
    if meta is None:
        return None
    spec = ScenarioSpec.model_validate_json(meta["spec"])
    if scenario_digest(spec) != meta["digest"]:
        raise ValueError(f"digest mismatch for scenario {sid}")
    res_item = by_sk.get(f"RESULT#{model_version}")
    result = orjson.loads(res_item["result"]) if res_item else None
    views = int(by_sk.get("STATS", {}).get("views", 0))
    if count_view:
        views = increment_views(sid)
    return CachedScenario(
        id=sid,
        spec=spec,
        result=_plain(result),
        views=views,
        created_at=meta["created_at"],
        cache_hit=result is not None,
    )


def increment_views(sid: str) -> int:
    out = get_table().update_item(
        Key={"PK": _pk(sid), "SK": "STATS"},
        UpdateExpression="ADD #v :one SET last_viewed_at = :now",
        ExpressionAttributeNames={"#v": "views"},
        ExpressionAttributeValues={
            ":one": 1,
            ":now": datetime.now(UTC).isoformat(timespec="seconds"),
        },
        ReturnValues="UPDATED_NEW",
    )
    return int(out["Attributes"]["views"])


def list_recent(season: int, round: int, limit: int = 20) -> list[dict]:
    """Most recent scenarios for a race via GSI1 (newest first)."""
    out = get_table().query(
        IndexName=GSI1,
        KeyConditionExpression=Key("GSI1PK").eq(f"RACE#{season}#{round:02d}"),
        ScanIndexForward=False,
        Limit=limit,
    )
    return [
        {"id": it["id"], "created_at": it["created_at"], "spec": orjson.loads(it["spec"])}
        for it in out["Items"]
    ]
