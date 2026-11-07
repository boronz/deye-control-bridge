"""Mutable runtime state shared by the entities and the coordinator."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class DeyeRuntime:
    """The values the user (or a HEMS) asked for.

    Kept outside the entities so the coordinator can read them without looking
    up entity states, and so a reload of the entities does not lose them.
    """

    input_power: float = 0.0
    export_power: float = 0.0
    min_soc: float = 20.0
    max_soc: float = 100.0
    enabled: bool = False
    allow_battery_export: bool = True
    conflict_policy: str = "charge_priority"
    mode: str = "manual"                # manual | self_consumption

    def reset_setpoints(self) -> None:
        self.input_power = 0.0
        self.export_power = 0.0
