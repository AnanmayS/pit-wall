"""What If scenario specification.

A scenario is a real race plus a list of changes applied at a branch lap. The spec is canonicalized
and hashed into a deterministic id (see ids.py), which is also the share-link id and the cache key.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

ChangeType = Literal[
    "pit_lap",  # move a driver's stop to `lap` (optionally with `compound`)
    "compound",  # change the compound fitted at stop number `stop`
    "skip_stop",  # remove stop number `stop`
    "extra_stop",  # add a stop on `lap` with `compound`
    "no_safety_car",  # suppress all safety cars after the branch lap
    "safety_car",  # force a safety car on `lap`
    "dnf",  # retire `driver` on `lap`
]


class Change(BaseModel):
    type: ChangeType
    driver: str | None = Field(
        default=None, description="3-letter code, required for driver changes"
    )
    lap: int | None = Field(default=None, ge=1)
    stop: int | None = Field(default=None, ge=1, description="1-based stop number")
    compound: str | None = None

    @model_validator(mode="after")
    def _check(self):
        driver_types = {"pit_lap", "compound", "skip_stop", "extra_stop", "dnf"}
        if self.type in driver_types and not self.driver:
            raise ValueError(f"{self.type} requires a driver")
        if self.type in {"pit_lap", "extra_stop", "safety_car", "dnf"} and self.lap is None:
            raise ValueError(f"{self.type} requires a lap")
        if self.type in {"compound", "skip_stop"} and self.stop is None:
            raise ValueError(f"{self.type} requires a stop number")
        if self.type in {"compound", "extra_stop"} and not self.compound:
            raise ValueError(f"{self.type} requires a compound")
        if self.driver:
            self.driver = self.driver.upper()
        if self.compound:
            self.compound = self.compound.upper()
        return self


class ScenarioSpec(BaseModel):
    season: int = Field(ge=1950)
    round: int = Field(ge=1, le=99)
    changes: list[Change] = Field(min_length=1, max_length=10)
    branch_lap: int | None = Field(
        default=None,
        ge=1,
        description="Lap from which to simulate; defaults to the earliest change",
    )
    n_runs: int = Field(default=10_000, ge=100, le=100_000)
    model_version: str = "sim-v1"

    def effective_branch_lap(self) -> int:
        if self.branch_lap is not None:
            return self.branch_lap
        laps = [c.lap for c in self.changes if c.lap is not None]
        return min(laps) if laps else 1
