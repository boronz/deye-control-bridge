"""Transport layer: Solarman V5 sticks and plain Modbus TCP gateways.

Both expose the same two operations, so the coordinator does not care which one
is in use.  All calls are blocking and are run in an executor by the caller.
"""

from __future__ import annotations

import logging
import threading

from .const import (
    CONF_HOST,
    CONF_PORT,
    CONF_SERIAL,
    CONF_TRANSPORT,
    CONF_UNIT_ID,
    TRANSPORT_MODBUS,
    TRANSPORT_SOLARMAN,
)

_LOGGER = logging.getLogger(__name__)


class TransportError(Exception):
    """The inverter could not be reached or rejected the request."""


class BaseTransport:
    """Minimal holding-register interface."""

    def read_holding(self, address: int, count: int) -> list[int]:
        raise NotImplementedError

    def write_holding(self, address: int, values: list[int]) -> None:
        raise NotImplementedError

    def close(self) -> None:
        """Release the connection (best effort)."""

    def test(self) -> int:
        """Read the battery SOC as a connectivity check. Returns the value."""
        return self.read_holding(588, 1)[0]


class SolarmanV5Transport(BaseTransport):
    """Stock Deye/Solarman dongle, TCP 8899, Solarman V5 framing."""

    def __init__(
        self,
        host: str,
        port: int,
        serial: int,
        unit_id: int = 1,
        timeout: int = 10,
    ) -> None:
        self.host = host
        self.port = int(port)
        self.serial = int(serial)
        self.unit_id = int(unit_id)
        self.timeout = int(timeout)
        self._lock = threading.Lock()
        self._client = None
        with self._lock:
            self._ensure()

    # -- internals ---------------------------------------------------------
    def _ensure(self) -> None:
        if self._client is not None:
            return
        try:
            from pysolarmanv5 import PySolarmanV5
        except ImportError as exc:  # pragma: no cover - depends on HA env
            raise TransportError("pysolarmanv5 is not installed") from exc
        self._client = PySolarmanV5(
            self.host,
            self.serial,
            port=self.port,
            mb_slave_id=self.unit_id,
            verbose=False,
            socket_timeout=self.timeout,
        )

    def _reset(self) -> None:
        client, self._client = self._client, None
        if client is not None:
            try:
                client.disconnect()
            except Exception:  # noqa: BLE001 - best effort
                pass

    def _call(self, function, *args):
        with self._lock:
            last_error: Exception | None = None
            for _attempt in range(2):
                try:
                    self._ensure()
                    return function(self._client, *args)
                except Exception as exc:  # noqa: BLE001 - library raises broadly
                    last_error = exc
                    self._reset()
            raise TransportError(str(last_error)) from last_error

    # -- API ---------------------------------------------------------------
    def read_holding(self, address: int, count: int) -> list[int]:
        result = self._call(
            lambda client, a, c: client.read_holding_registers(a, c),
            int(address),
            int(count),
        )
        return [int(value) for value in result]

    def write_holding(self, address: int, values: list[int]) -> None:
        self._call(
            lambda client, a, v: client.write_multiple_holding_registers(a, v),
            int(address),
            [int(value) for value in values],
        )

    def close(self) -> None:
        with self._lock:
            self._reset()


class ModbusTcpTransport(BaseTransport):
    """Plain Modbus TCP, e.g. an RS485-to-Ethernet gateway on port 502."""

    def __init__(
        self,
        host: str,
        port: int,
        unit_id: int = 1,
        timeout: int = 10,
    ) -> None:
        self.host = host
        self.port = int(port)
        self.unit_id = int(unit_id)
        self.timeout = int(timeout)
        self._lock = threading.Lock()
        self._client = None
        with self._lock:
            self._ensure()

    # -- internals ---------------------------------------------------------
    def _ensure(self) -> None:
        if self._client is not None:
            return
        try:
            from pymodbus.client import ModbusTcpClient
        except ImportError as exc:  # pragma: no cover - depends on HA env
            raise TransportError("pymodbus is not installed") from exc
        client = ModbusTcpClient(self.host, port=self.port, timeout=self.timeout)
        if not client.connect():
            raise TransportError(f"cannot connect to {self.host}:{self.port}")
        self._client = client

    def _reset(self) -> None:
        client, self._client = self._client, None
        if client is not None:
            try:
                client.close()
            except Exception:  # noqa: BLE001 - best effort
                pass

    def _call(self, function, *args, **kwargs):
        with self._lock:
            last_error: Exception | None = None
            for _attempt in range(2):
                try:
                    self._ensure()
                    return function(self._client, *args, **kwargs)
                except Exception as exc:  # noqa: BLE001 - library raises broadly
                    last_error = exc
                    self._reset()
            raise TransportError(str(last_error)) from last_error

    def _read(self, address: int, count: int):
        try:
            return self._client.read_holding_registers(
                address, count=count, slave=self.unit_id
            )
        except TypeError:
            # pymodbus 2.x called the parameter "unit"
            return self._client.read_holding_registers(
                address, count=count, unit=self.unit_id
            )

    def _write(self, address: int, values: list[int]):
        try:
            return self._client.write_registers(
                address, values=values, slave=self.unit_id
            )
        except TypeError:
            return self._client.write_registers(
                address, values=values, unit=self.unit_id
            )

    # -- API ---------------------------------------------------------------
    def read_holding(self, address: int, count: int) -> list[int]:
        result = self._call(self._read, int(address), int(count))
        if result.isError():
            raise TransportError(f"Modbus error reading {address}: {result}")
        return [int(value) for value in result.registers]

    def write_holding(self, address: int, values: list[int]) -> None:
        result = self._call(
            self._write, int(address), [int(value) for value in values]
        )
        if result.isError():
            raise TransportError(f"Modbus error writing {address}: {result}")

    def close(self) -> None:
        with self._lock:
            self._reset()


def create_transport(config: dict) -> BaseTransport:
    """Build the transport described by a config entry (blocking)."""
    transport = config[CONF_TRANSPORT]
    unit_id = int(config.get(CONF_UNIT_ID, 1))

    if transport == TRANSPORT_SOLARMAN:
        serial = config.get(CONF_SERIAL)
        if not serial:
            raise TransportError("a logger serial number is required for Solarman V5")
        return SolarmanV5Transport(
            config[CONF_HOST],
            int(config[CONF_PORT]),
            int(serial),
            unit_id=unit_id,
        )

    if transport == TRANSPORT_MODBUS:
        return ModbusTcpTransport(
            config[CONF_HOST],
            int(config[CONF_PORT]),
            unit_id=unit_id,
        )

    raise TransportError(f"unknown transport {transport!r}")
