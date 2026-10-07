"""Deterministic scenario ids: id = base62(sha256(canonical_json)[:10 bytes]).

Canonical JSON: sorted keys, no whitespace, changes sorted by their own canonical form, defaults
filled in. The same scenario always maps to the same id, so the id doubles as cache key and share
link. The full hex digest is stored alongside and checked on read.
"""

from __future__ import annotations

import hashlib
import json

from pitwall.whatif.models import ScenarioSpec

_ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
ID_BYTES = 10


def _b62(data: bytes) -> str:
    n = int.from_bytes(data, "big")
    out = []
    while n:
        n, r = divmod(n, 62)
        out.append(_ALPHABET[r])
    return "".join(reversed(out)) or "0"


def canonical_json(spec: ScenarioSpec) -> str:
    payload = spec.model_dump(mode="json")
    payload["branch_lap"] = spec.effective_branch_lap()
    changes = [json.dumps(c, sort_keys=True, separators=(",", ":")) for c in payload["changes"]]
    payload["changes"] = [json.loads(c) for c in sorted(changes)]
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def scenario_digest(spec: ScenarioSpec) -> str:
    return hashlib.sha256(canonical_json(spec).encode()).hexdigest()


def scenario_id(spec: ScenarioSpec) -> str:
    digest = hashlib.sha256(canonical_json(spec).encode()).digest()
    return _b62(digest[:ID_BYTES])
