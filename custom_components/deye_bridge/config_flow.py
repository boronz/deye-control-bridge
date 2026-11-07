"""Config and options flow for the Deye Power Bridge."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, OptionsFlow
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import config_validation as cv

from .const import (
    CONF_ABSORB_ENTER_HOLD,
    CONF_ABSORB_ENTER_POWER,
    CONF_ABSORB_EXIT_HOLD,
    CONF_ABSORB_EXIT_POWER,
    CONF_ABSORB_INTERVAL,
    CONF_ABSORB_RATIO,
    CONF_BASE_MODE,
    CONF_CURRENT_DEADBAND,
    CONF_EXPORT_DEADBAND,
    CONF_HOST,
    CONF_MANAGE_CHARGE_CURRENT,
    CONF_MAX_CHARGE_CURRENT,
    CONF_MAX_DISCHARGE_CURRENT,
    CONF_MAX_EXPORT_POWER,
    CONF_MAX_GRID_CHARGE_POWER,
    CONF_PORT,
    CONF_SCAN_INTERVAL,
    CONF_SERIAL,
    CONF_TRANSPORT,
    CONF_UNIT_ID,
    CONF_VERIFY_EVERY,
    DEFAULT_ABSORB_ENTER_HOLD,
    DEFAULT_ABSORB_ENTER_POWER,
    DEFAULT_ABSORB_EXIT_HOLD,
    DEFAULT_ABSORB_EXIT_POWER,
    DEFAULT_ABSORB_INTERVAL,
    DEFAULT_ABSORB_RATIO,
    DEFAULT_BASE_MODE,
    DEFAULT_CURRENT_DEADBAND,
    DEFAULT_EXPORT_DEADBAND,
    DEFAULT_MANAGE_CHARGE_CURRENT,
    DEFAULT_MAX_CHARGE_CURRENT,
    DEFAULT_MAX_DISCHARGE_CURRENT,
    DEFAULT_MAX_EXPORT_POWER,
    DEFAULT_MAX_GRID_CHARGE_POWER,
    DEFAULT_PORT,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_UNIT_ID,
    DEFAULT_VERIFY_EVERY,
    DOMAIN,
    TRANSPORT_MODBUS,
    TRANSPORT_SOLARMAN,
    TRANSPORTS,
)
from .transport import TransportError, create_transport

_LOGGER = logging.getLogger(__name__)

BASE_MODES = {
    0: "Selling First",
    1: "Zero Export To Load (built-in CT)",
    2: "Zero Export To CT (external CT)",
}


def _validate(config: dict) -> int:
    """Connect and read the SOC; return it. Blocking, run in executor."""
    transport = create_transport(config)
    try:
        soc = transport.test()
    finally:
        transport.close()
    if not 0 <= soc <= 100:
        raise TransportError(f"unexpected SOC value {soc}")
    return soc


class DeyeBridgeConfigFlow(ConfigFlow, domain=DOMAIN):
    """Two steps: transport, then connection details."""

    VERSION = 1

    def __init__(self) -> None:
        self._transport: str = TRANSPORT_SOLARMAN

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        if user_input is not None:
            self._transport = user_input[CONF_TRANSPORT]
            return await self.async_step_connection()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_TRANSPORT, default=TRANSPORT_SOLARMAN): vol.In(
                        {
                            TRANSPORT_SOLARMAN: "Solarman V5 (stock Wi-Fi/LAN dongle, port 8899)",
                            TRANSPORT_MODBUS: "Plain Modbus TCP (RS485-to-Ethernet gateway, port 502)",
                        }
                    )
                }
            ),
        )

    async def async_step_connection(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            config = {**user_input, CONF_TRANSPORT: self._transport}
            unique_id = "{transport}_{host}_{port}_{serial}_{unit}".format(
                transport=self._transport,
                host=config[CONF_HOST],
                port=config[CONF_PORT],
                serial=config.get(CONF_SERIAL, 0),
                unit=config[CONF_UNIT_ID],
            )
            await self.async_set_unique_id(unique_id)
            self._abort_if_unique_id_configured()

            try:
                await self.hass.async_add_executor_job(_validate, config)
            except TransportError as exc:
                _LOGGER.warning("Connection test failed: %s", exc)
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001 - unexpected library errors
                _LOGGER.exception("Unexpected error while connecting")
                errors["base"] = "unknown"
            else:
                return self.async_create_entry(title="Deye inverter", data=config)

        fields: dict[Any, Any] = {
            vol.Required(CONF_HOST): cv.string,
            vol.Required(
                CONF_PORT, default=DEFAULT_PORT[self._transport]
            ): cv.port,
            vol.Required(CONF_UNIT_ID, default=DEFAULT_UNIT_ID): vol.All(
                vol.Coerce(int), vol.Range(min=1, max=247)
            ),
            vol.Required(
                CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL
            ): vol.All(vol.Coerce(int), vol.Range(min=10, max=300)),
        }
        if self._transport == TRANSPORT_SOLARMAN:
            fields[vol.Required(CONF_SERIAL)] = cv.positive_int

        return self.async_show_form(
            step_id="connection",
            data_schema=vol.Schema(fields),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return DeyeBridgeOptionsFlow()


class DeyeBridgeOptionsFlow(OptionsFlow):
    """Limits, work mode and write behaviour."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            if user_input[CONF_ABSORB_EXIT_POWER] > user_input[CONF_ABSORB_ENTER_POWER]:
                errors["base"] = "invalid_absorption"
            else:
                return self.async_create_entry(title="", data=user_input)

        options = {**self.config_entry.data, **self.config_entry.options}

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_MAX_GRID_CHARGE_POWER,
                    default=options.get(
                        CONF_MAX_GRID_CHARGE_POWER, DEFAULT_MAX_GRID_CHARGE_POWER
                    ),
                ): vol.All(vol.Coerce(int), vol.Range(min=0, max=20000)),
                vol.Required(
                    CONF_MAX_EXPORT_POWER,
                    default=options.get(CONF_MAX_EXPORT_POWER, DEFAULT_MAX_EXPORT_POWER),
                ): vol.All(vol.Coerce(int), vol.Range(min=0, max=30000)),
                vol.Required(
                    CONF_MAX_CHARGE_CURRENT,
                    default=options.get(
                        CONF_MAX_CHARGE_CURRENT, DEFAULT_MAX_CHARGE_CURRENT
                    ),
                ): vol.All(vol.Coerce(int), vol.Range(min=0, max=185)),
                vol.Required(
                    CONF_MAX_DISCHARGE_CURRENT,
                    default=options.get(
                        CONF_MAX_DISCHARGE_CURRENT, DEFAULT_MAX_DISCHARGE_CURRENT
                    ),
                ): vol.All(vol.Coerce(int), vol.Range(min=0, max=185)),
                vol.Required(
                    CONF_BASE_MODE,
                    default=options.get(CONF_BASE_MODE, DEFAULT_BASE_MODE),
                ): vol.In(BASE_MODES),
                vol.Required(
                    CONF_MANAGE_CHARGE_CURRENT,
                    default=options.get(
                        CONF_MANAGE_CHARGE_CURRENT, DEFAULT_MANAGE_CHARGE_CURRENT
                    ),
                ): cv.boolean,
                vol.Required(
                    CONF_CURRENT_DEADBAND,
                    default=options.get(
                        CONF_CURRENT_DEADBAND, DEFAULT_CURRENT_DEADBAND
                    ),
                ): vol.All(vol.Coerce(int), vol.Range(min=0, max=20)),
                vol.Required(
                    CONF_EXPORT_DEADBAND,
                    default=options.get(
                        CONF_EXPORT_DEADBAND, DEFAULT_EXPORT_DEADBAND
                    ),
                ): vol.All(vol.Coerce(int), vol.Range(min=0, max=1000)),
                vol.Required(
                    CONF_VERIFY_EVERY,
                    default=options.get(CONF_VERIFY_EVERY, DEFAULT_VERIFY_EVERY),
                ): vol.All(vol.Coerce(int), vol.Range(min=0, max=100)),
                vol.Required(
                    CONF_SCAN_INTERVAL,
                    default=options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
                ): vol.All(vol.Coerce(int), vol.Range(min=10, max=300)),
                vol.Required(
                    CONF_ABSORB_INTERVAL,
                    default=options.get(CONF_ABSORB_INTERVAL, DEFAULT_ABSORB_INTERVAL),
                ): vol.All(vol.Coerce(int), vol.Range(min=0, max=60)),
                vol.Required(
                    CONF_ABSORB_ENTER_POWER,
                    default=options.get(
                        CONF_ABSORB_ENTER_POWER, DEFAULT_ABSORB_ENTER_POWER
                    ),
                ): vol.All(vol.Coerce(int), vol.Range(min=0, max=5000)),
                vol.Required(
                    CONF_ABSORB_EXIT_POWER,
                    default=options.get(
                        CONF_ABSORB_EXIT_POWER, DEFAULT_ABSORB_EXIT_POWER
                    ),
                ): vol.All(vol.Coerce(int), vol.Range(min=0, max=5000)),
                vol.Required(
                    CONF_ABSORB_ENTER_HOLD,
                    default=options.get(
                        CONF_ABSORB_ENTER_HOLD, DEFAULT_ABSORB_ENTER_HOLD
                    ),
                ): vol.All(vol.Coerce(int), vol.Range(min=0, max=600)),
                vol.Required(
                    CONF_ABSORB_EXIT_HOLD,
                    default=options.get(
                        CONF_ABSORB_EXIT_HOLD, DEFAULT_ABSORB_EXIT_HOLD
                    ),
                ): vol.All(vol.Coerce(int), vol.Range(min=0, max=600)),
                vol.Required(
                    CONF_ABSORB_RATIO,
                    default=options.get(CONF_ABSORB_RATIO, DEFAULT_ABSORB_RATIO),
                ): vol.All(vol.Coerce(float), vol.Range(min=0.5, max=1.0)),
            }
        )

        return self.async_show_form(step_id="init", data_schema=schema, errors=errors)
