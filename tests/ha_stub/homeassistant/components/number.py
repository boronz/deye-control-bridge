from dataclasses import dataclass
from . import EntityDescription

class NumberEntity:
    async def async_set_native_value(self, value): pass

class NumberMode:
    BOX = "box"; SLIDER = "slider"

@dataclass(frozen=True, kw_only=True)
class NumberEntityDescription(EntityDescription):
    native_min_value: float = 0.0
    native_max_value: float = 100.0
    native_step: float = 1.0
    native_unit_of_measurement: str | None = None
    mode: str | None = None
