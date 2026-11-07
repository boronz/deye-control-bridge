"""The Deye Power Bridge integration."""

from __future__ import annotations

import logging
import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from homeassistant.core import Event, HomeAssistant, ServiceCall
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv

from .const import (
    ATTR_ENTRY_ID,
    DOMAIN,
    PLATFORMS,
    SERVICE_APPLY,
    SERVICE_RESTORE,
    SERVICE_SNAPSHOT,
)
from .coordinator import DeyeCoordinator
from .runtime import DeyeRuntime
from .transport import TransportError, create_transport

_LOGGER = logging.getLogger(__name__)

SERVICE_SCHEMA = vol.Schema({vol.Optional(ATTR_ENTRY_ID): cv.string})


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Register the domain-level services once."""
    hass.data.setdefault(DOMAIN, {})
    _async_register_services(hass)

    async def _restore_on_stop(event: Event) -> None:
        for coordinator in list(hass.data.get(DOMAIN, {}).values()):
            await coordinator.async_shutdown()

    hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, _restore_on_stop)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up one inverter."""
    store = hass.data.setdefault(DOMAIN, {})

    # Reuse the runtime across an options reload so the setpoints survive.
    previous = store.get(entry.entry_id)
    runtime = previous.runtime if isinstance(previous, DeyeCoordinator) else DeyeRuntime()

    try:
        transport = await hass.async_add_executor_job(create_transport, dict(entry.data))
    except TransportError as exc:
        raise ConfigEntryNotReady(str(exc)) from exc

    coordinator = DeyeCoordinator(hass, entry, transport, runtime)

    try:
        await coordinator.async_load_snapshot()
        await coordinator.async_config_entry_first_refresh()
    except Exception:
        await hass.async_add_executor_job(transport.close)
        raise

    entry.runtime_data = coordinator
    store[entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload one inverter and close its connection."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if not unload_ok:
        return False

    coordinator: DeyeCoordinator | None = hass.data.get(DOMAIN, {}).pop(
        entry.entry_id, None
    )
    if coordinator is not None:
        if coordinator.runtime.enabled:
            try:
                await coordinator.async_restore()
            except Exception as exc:  # noqa: BLE001 - removal must not fail
                _LOGGER.warning("Restore on unload failed: %s", exc)
        await hass.async_add_executor_job(coordinator.transport.close)
    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Apply options changes in place (no reload, so setpoints survive)."""
    coordinator: DeyeCoordinator | None = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if coordinator is None:
        return
    coordinator.apply_options({**entry.data, **entry.options})
    await coordinator.async_request_refresh()


def _coordinators(hass: HomeAssistant, call: ServiceCall) -> list[DeyeCoordinator]:
    entries = hass.data.get(DOMAIN, {})
    entry_id = call.data.get(ATTR_ENTRY_ID)
    if entry_id:
        coordinator = entries.get(entry_id)
        return [coordinator] if coordinator else []
    return [c for c in entries.values() if isinstance(c, DeyeCoordinator)]


def _async_register_services(hass: HomeAssistant) -> None:
    async def handle_snapshot(call: ServiceCall) -> None:
        for coordinator in _coordinators(hass, call):
            await coordinator.async_snapshot()

    async def handle_restore(call: ServiceCall) -> None:
        for coordinator in _coordinators(hass, call):
            await coordinator.async_restore()

    async def handle_apply(call: ServiceCall) -> None:
        for coordinator in _coordinators(hass, call):
            await coordinator.async_apply_now()

    if not hass.services.has_service(DOMAIN, SERVICE_SNAPSHOT):
        hass.services.async_register(
            DOMAIN, SERVICE_SNAPSHOT, handle_snapshot, schema=SERVICE_SCHEMA
        )
    if not hass.services.has_service(DOMAIN, SERVICE_RESTORE):
        hass.services.async_register(
            DOMAIN, SERVICE_RESTORE, handle_restore, schema=SERVICE_SCHEMA
        )
    if not hass.services.has_service(DOMAIN, SERVICE_APPLY):
        hass.services.async_register(
            DOMAIN, SERVICE_APPLY, handle_apply, schema=SERVICE_SCHEMA
        )
