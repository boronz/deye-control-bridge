from dataclasses import dataclass
from typing import Any
from . import EntityDescription

class SensorEntity: pass

class SensorDeviceClass:
    BATTERY = "battery"; VOLTAGE = "voltage"; POWER = "power"; ENUM = "enum"; ENERGY = "energy"

class SensorStateClass:
    MEASUREMENT = "measurement"; TOTAL_INCREASING = "total_increasing"

@dataclass(frozen=True, kw_only=True)
class SensorEntityDescription(EntityDescription):
    native_unit_of_measurement: str | None = None
    state_class: Any = None
    options: list[str] | None = None
