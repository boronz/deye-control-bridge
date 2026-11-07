"""Select entity: what to do when both sliders are above zero."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import CONFLICT_POLICIES
from .core import OPERATING_MODES
from .coordinator import DeyeCoordinator
from .entity import DeyeEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: DeyeCoordinator = entry.runtime_data
    async_add_entities(
        [
            DeyeModeSelect(coordinator),
            DeyeConflictPolicySelect(coordinator),
        ]
    )


class DeyeModeSelect(DeyeEntity, SelectEntity, RestoreEntity):
    """manual (sliders) or self_consumption (absorb AC-coupled export)."""

    _attr_name = "Operating mode"
    _attr_icon = "mdi:auto-mode"
    _attr_options = list(OPERATING_MODES)

    def __init__(self, coordinator: DeyeCoordinator) -> None:
        super().__init__(coordinator, "mode")

    @property
    def current_option(self) -> str:
        return self.coordinator.runtime.mode

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is not None and last_state.state in OPERATING_MODES:
            self.coordinator.runtime.mode = last_state.state
            self.async_write_ha_state()

    async def async_select_option(self, option: str) -> None:
        if option not in OPERATING_MODES:
            raise ValueError(f"Unsupported operating mode: {option}")
        self.coordinator.runtime.mode = option
        self.async_write_ha_state()
        await self.coordinator.async_apply_now()


class DeyeConflictPolicySelect(DeyeEntity, SelectEntity, RestoreEntity):
    """charge_priority / export_priority / net."""

    _attr_name = "Both-sliders policy"
    _attr_icon = "mdi:source-branch"
    _attr_options = CONFLICT_POLICIES

    def __init__(self, coordinator: DeyeCoordinator) -> None:
        super().__init__(coordinator, "conflict_policy")

    @property
    def current_option(self) -> str:
        return self.coordinator.runtime.conflict_policy

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is not None and last_state.state in CONFLICT_POLICIES:
            self.coordinator.runtime.conflict_policy = last_state.state
            self.async_write_ha_state()

    async def async_select_option(self, option: str) -> None:
        if option not in CONFLICT_POLICIES:
            raise ValueError(f"Unsupported conflict policy: {option}")
        self.coordinator.runtime.conflict_policy = option
        self.async_write_ha_state()
        await self.coordinator.async_apply_now()
