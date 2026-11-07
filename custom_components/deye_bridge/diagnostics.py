"""Diagnostics support for the Deye Power Bridge."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_SERIAL, DOMAIN
from .coordinator import DeyeCoordinator


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for one inverter."""
    coordinator: DeyeCoordinator | None = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    data = coordinator.data if coordinator else None

    config = dict(entry.data)
    if CONF_SERIAL in config:
        config[CONF_SERIAL] = "**redacted**"

    return {
        "config": config,
        "options": dict(entry.options),
        "runtime": asdict(coordinator.runtime) if coordinator else None,
        "state": data.state if data else None,
        "reason": data.reason if data else None,
        "last_error": data.last_error if data else None,
        "measurements": {
            "battery_soc": data.battery_soc if data else None,
            "battery_voltage": data.battery_voltage if data else None,
            "battery_power": data.battery_power if data else None,
            "grid_power": data.grid_power if data else None,
            "pv_power": data.pv_power if data else None,
            "load_power": data.load_power if data else None,
        },
        "applied_registers": coordinator.applied_registers if coordinator else None,
        "has_snapshot": coordinator.has_snapshot if coordinator else None,
    }
