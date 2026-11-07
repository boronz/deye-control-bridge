from dataclasses import dataclass
from typing import Any

@dataclass(frozen=True, kw_only=True)
class EntityDescription:
    key: str | None = None
    translation_key: str | None = None
    name: str | None = None
    icon: str | None = None
    device_class: Any = None
    entity_category: Any = None
    entity_registry_enabled_default: bool = True
