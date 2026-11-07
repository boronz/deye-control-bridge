"""Data coordinator: poll the inverter, run the translation, write the changes."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    CONF_BASE_MODE,
    CONF_CURRENT_DEADBAND,
    CONF_EXPORT_DEADBAND,
    CONF_MANAGE_CHARGE_CURRENT,
    CONF_MAX_CHARGE_CURRENT,
    CONF_MAX_DISCHARGE_CURRENT,
    CONF_MAX_EXPORT_POWER,
    CONF_MAX_GRID_CHARGE_POWER,
    CONF_SCAN_INTERVAL,
    CONF_VERIFY_EVERY,
    DEFAULT_BASE_MODE,
    DEFAULT_CURRENT_DEADBAND,
    DEFAULT_EXPORT_DEADBAND,
    DEFAULT_MANAGE_CHARGE_CURRENT,
    DEFAULT_MAX_CHARGE_CURRENT,
    DEFAULT_MAX_DISCHARGE_CURRENT,
    DEFAULT_MAX_EXPORT_POWER,
    DEFAULT_MAX_GRID_CHARGE_POWER,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_VERIFY_EVERY,
    DOMAIN,
    STORAGE_KEY,
    STORAGE_VERSION,
)
from .core import (
    REG_GRID_CHARGE_CURRENT,
    REG_GRID_CHARGE_ENABLE,
    REG_MAX_DISCHARGE_CURRENT,
    REG_MAX_SELL_POWER,
    REG_SOLAR_SELL,
    REG_TOU_ENABLE,
    REG_WORK_MODE,
    Config,
    Inputs,
    build_plan,
)
from .runtime import DeyeRuntime
from .transport import BaseTransport, TransportError

_LOGGER = logging.getLogger(__name__)

# Registers we may write, used for snapshot / restore.
SNAPSHOT_SINGLE = [108, 109, 127, 128, 130, 142, 143, 145, 146]
SNAPSHOT_BLOCKS = [(154, 6), (166, 6), (172, 6)]

MIN_WRITE_INTERVAL_S = 5.0


def _s16(value: int) -> int:
    """Decode a two's-complement 16-bit register."""
    return value - 0x10000 if value >= 0x8000 else value


def _u32(low: int, high: int) -> int:
    """Deye energy counters are 32-bit, low word first."""
    return (high << 16) | low


@dataclass
class DeyeData:
    """A poll result plus the plan that was applied to it."""

    battery_soc: float
    battery_voltage: float
    battery_power: float
    grid_power: float
    pv_power: float
    load_power: float
    state: str
    reason: str
    charge_current_a: float
    export_power_w: float
    energy: dict[str, float] = field(default_factory=dict)
    last_error: str | None = None

    @property
    def applied_charge_power(self) -> float:
        return round(self.charge_current_a * self.battery_voltage)

    @property
    def is_connected(self) -> bool:
        return self.last_error is None


class DeyeCoordinator(DataUpdateCoordinator[DeyeData]):
    """Polls measurements, translates the setpoints and writes the result."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        transport: BaseTransport,
        runtime: DeyeRuntime,
    ) -> None:
        self.entry = entry
        self.transport = transport
        self.runtime = runtime
        self.options = {**entry.data, **entry.options}
        self._io_lock = asyncio.Lock()
        self._applied: dict[int, tuple[int, ...]] = {}
        self._last_write: dict[int, float] = {}
        self._snapshot: dict[int, tuple[int, ...]] | None = None
        self._cycle = 0
        self._state = "idle"
        self._last_error: str | None = None

        scan = int(self.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL))
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=scan),
        )
        self._store: Store = Store(
            hass,
            STORAGE_VERSION,
            STORAGE_KEY.format(entry_id=entry.entry_id),
        )

    # ------------------------------------------------------------------
    # Translation configuration
    # ------------------------------------------------------------------
    def _config(self) -> Config:
        return Config(
            max_grid_charge_power_w=int(
                self.options.get(CONF_MAX_GRID_CHARGE_POWER, DEFAULT_MAX_GRID_CHARGE_POWER)
            ),
            max_export_power_w=int(
                self.options.get(CONF_MAX_EXPORT_POWER, DEFAULT_MAX_EXPORT_POWER)
            ),
            max_charge_current_a=int(
                self.options.get(CONF_MAX_CHARGE_CURRENT, DEFAULT_MAX_CHARGE_CURRENT)
            ),
            max_discharge_current_a=int(
                self.options.get(CONF_MAX_DISCHARGE_CURRENT, DEFAULT_MAX_DISCHARGE_CURRENT)
            ),
            base_mode=int(self.options.get(CONF_BASE_MODE, DEFAULT_BASE_MODE)),
            manage_max_charge_current=bool(
                self.options.get(CONF_MANAGE_CHARGE_CURRENT, DEFAULT_MANAGE_CHARGE_CURRENT)
            ),
            conflict_policy=self.runtime.conflict_policy,
        )

    def _inputs(self, raw: dict[str, float]) -> Inputs:
        return Inputs(
            charge_power_w=self.runtime.input_power,
            export_power_w=self.runtime.export_power,
            soc=raw.get("soc"),
            battery_voltage=raw.get("voltage"),
            enabled=self.runtime.enabled,
            allow_battery_export=self.runtime.allow_battery_export,
            min_soc=self.runtime.min_soc,
            max_soc=self.runtime.max_soc,
            conflict_policy=self.runtime.conflict_policy,
        )

    # ------------------------------------------------------------------
    # Blocking I/O (run in the executor)
    # ------------------------------------------------------------------
    def _read_all(self) -> dict:
        battery = self.transport.read_holding(587, 5)     # 587..591
        grid = self.transport.read_holding(625, 29)       # 625..653
        pv = self.transport.read_holding(672, 2)          # 672..673
        energy_block = self.transport.read_holding(514, 16)   # 514..529
        pv_total = self.transport.read_holding(534, 2)        # 534..535

        energy = {
            "battery_charge_today": energy_block[0] * 0.1,
            "battery_discharge_today": energy_block[1] * 0.1,
            "battery_charge_total": _u32(energy_block[2], energy_block[3]) * 0.1,
            "battery_discharge_total": _u32(energy_block[4], energy_block[5]) * 0.1,
            "grid_buy_today": energy_block[6] * 0.1,
            "grid_sell_today": energy_block[7] * 0.1,
            "grid_buy_total": _u32(energy_block[8], energy_block[9]) * 0.1,
            "grid_sell_total": _u32(energy_block[10], energy_block[11]) * 0.1,
            "load_today": energy_block[12] * 0.1,
            "load_total": _u32(energy_block[13], energy_block[14]) * 0.1,
            "pv_today": energy_block[15] * 0.1,
            "pv_total": _u32(pv_total[0], pv_total[1]) * 0.1,
        }

        return {
            "voltage": battery[0] / 100.0,
            "soc": float(battery[1]),
            "battery_power": float(_s16(battery[3])),
            "grid_power": float(_s16(grid[0])),
            "load_power": float(_s16(grid[28])),
            "pv_power": float(pv[0] + pv[1]),
            "energy": energy,
        }

    def _deadband(self, address: int) -> float:
        if address == REG_GRID_CHARGE_CURRENT:
            return float(self.options.get(CONF_CURRENT_DEADBAND, DEFAULT_CURRENT_DEADBAND))
        if address == REG_MAX_SELL_POWER:
            return float(self.options.get(CONF_EXPORT_DEADBAND, DEFAULT_EXPORT_DEADBAND))
        return 0.0

    def _execute(self, plan) -> int:
        written = 0
        for write in plan.writes:
            address = write.address
            values = tuple(int(value) for value in write.values)
            previous = self._applied.get(address)

            if previous == values:
                continue
            if previous is not None and len(previous) == len(values):
                band = self._deadband(address)
                if band and all(abs(a - b) <= band for a, b in zip(previous, values)):
                    continue

            # Only touch the global discharge current when holding the battery
            # (109 = 0) or undoing a hold.
            if address == REG_MAX_DISCHARGE_CURRENT and values != (0,):
                if self._applied.get(address) != (0,):
                    continue

            now = time.monotonic()
            if address in self._last_write and now - self._last_write[address] < MIN_WRITE_INTERVAL_S:
                continue

            try:
                self.transport.write_holding(address, list(values))
            except TransportError as exc:
                _LOGGER.error("Write %s=%s failed: %s", address, list(values), exc)
                self._applied.pop(address, None)
                self._last_error = str(exc)
                continue

            self._applied[address] = values
            self._last_write[address] = now
            written += 1

        if written:
            _LOGGER.debug("%s -> %s write(s): %s", plan.state, written, plan.describe())
        return written

    def _verify(self) -> None:
        try:
            registers = self.transport.read_holding(127, 20)  # 127..146
        except TransportError as exc:
            _LOGGER.warning("Verification read failed: %s", exc)
            return

        for address in (
            REG_GRID_CHARGE_CURRENT,
            REG_GRID_CHARGE_ENABLE,
            REG_MAX_SELL_POWER,
            REG_SOLAR_SELL,
            REG_WORK_MODE,
            REG_TOU_ENABLE,
        ):
            applied = self._applied.get(address)
            if applied is None:
                continue
            actual = (registers[address - 127],)
            if actual != applied:
                _LOGGER.warning(
                    "Drift at register %s: applied %s, inverter has %s; re-applying",
                    address, applied, actual,
                )
                self._applied.pop(address, None)

    def _read_snapshot(self) -> dict[int, tuple[int, ...]]:
        low = self.transport.read_holding(108, 23)    # 108..130
        high = self.transport.read_holding(142, 36)   # 142..177
        both = {108 + i: value for i, value in enumerate(low)}
        both.update({142 + i: value for i, value in enumerate(high)})

        snapshot: dict[int, tuple[int, ...]] = {}
        for address in SNAPSHOT_SINGLE:
            if address in both:
                snapshot[address] = (both[address],)
        for start, count in SNAPSHOT_BLOCKS:
            snapshot[start] = tuple(both.get(start + i, 0) for i in range(count))
        return snapshot

    def _write_snapshot(self, snapshot: dict[int, tuple[int, ...]]) -> None:
        for address, values in sorted(snapshot.items()):
            self.transport.write_holding(address, list(values))

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------
    async def async_load_snapshot(self) -> None:
        """Load a persisted snapshot into memory (no I/O to the inverter)."""
        try:
            stored = await self._store.async_load()
            if stored:
                self._snapshot = {
                    int(address): tuple(int(v) for v in values)
                    for address, values in stored.items()
                }
        except (TypeError, ValueError) as exc:
            _LOGGER.warning("Ignoring unreadable register snapshot: %s", exc)

    async def async_snapshot(self) -> dict[int, tuple[int, ...]]:
        async with self._io_lock:
            snapshot = await self.hass.async_add_executor_job(self._read_snapshot)
            self._snapshot = snapshot
            await self._store.async_save(
                {str(address): list(values) for address, values in snapshot.items()}
            )
            _LOGGER.info("Snapshot taken (%d register entries)", len(snapshot))
            return snapshot

    async def async_restore(self) -> bool:
        async with self._io_lock:
            snapshot = self._snapshot
            if snapshot is None:
                stored = await self._store.async_load()
                if stored:
                    snapshot = {
                        int(address): tuple(int(v) for v in values)
                        for address, values in stored.items()
                    }
            if not snapshot:
                _LOGGER.warning("Nothing to restore: no snapshot available")
                return False

            await self.hass.async_add_executor_job(self._write_snapshot, snapshot)
            self._applied.clear()
            _LOGGER.info("Restored %d register entries", len(snapshot))
            return True

    async def async_apply_now(self) -> None:
        await self.async_request_refresh()

    @property
    def has_snapshot(self) -> bool:
        return self._snapshot is not None

    @property
    def applied_registers(self) -> dict[str, list[int]]:
        return {str(address): list(values) for address, values in self._applied.items()}

    async def async_shutdown(self) -> None:
        """Best effort: put the inverter back before HA goes away."""
        if self.runtime.enabled:
            try:
                await self.async_restore()
            except Exception as exc:  # noqa: BLE001 - never block shutdown
                _LOGGER.warning("Restore on shutdown failed: %s", exc)

    # ------------------------------------------------------------------
    # Coordinator update
    # ------------------------------------------------------------------
    async def _async_update_data(self) -> DeyeData:
        async with self._io_lock:
            try:
                raw = await self.hass.async_add_executor_job(self._read_all)
                self._last_error = None
            except TransportError as exc:
                self._last_error = str(exc)
                raise UpdateFailed(str(exc)) from exc

            plan = build_plan(self._config(), self._inputs(raw))
            try:
                await self.hass.async_add_executor_job(self._execute, plan)
                verify_every = int(self.options.get(CONF_VERIFY_EVERY, DEFAULT_VERIFY_EVERY))
                if verify_every and self._cycle % verify_every == 0:
                    await self.hass.async_add_executor_job(self._verify)
            except TransportError as exc:
                _LOGGER.warning("Applying the plan failed: %s", exc)
                self._last_error = str(exc)

            self._cycle += 1
            self._state = plan.state

            return DeyeData(
                battery_soc=raw["soc"],
                battery_voltage=raw["voltage"],
                battery_power=raw["battery_power"],
                grid_power=raw["grid_power"],
                pv_power=raw["pv_power"],
                load_power=raw["load_power"],
                state=plan.state,
                reason=plan.reason,
                charge_current_a=plan.charge_current_a,
                export_power_w=plan.export_power_w,
                energy=raw["energy"],
                last_error=self._last_error,
            )
