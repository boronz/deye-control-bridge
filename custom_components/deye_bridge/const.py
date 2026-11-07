"""Constants for the Deye Power Bridge integration."""

from __future__ import annotations

from datetime import timedelta

DOMAIN = "deye_bridge"
NAME = "Deye Power Bridge"
VERSION = "0.1.0"

PLATFORMS = ["binary_sensor", "number", "select", "sensor", "switch"]

# --------------------------------------------------------------------------
# Config / options keys
# --------------------------------------------------------------------------
CONF_TRANSPORT = "transport"
CONF_HOST = "host"
CONF_PORT = "port"
CONF_SERIAL = "serial"
CONF_UNIT_ID = "unit_id"
CONF_SCAN_INTERVAL = "scan_interval"

CONF_MAX_GRID_CHARGE_POWER = "max_grid_charge_power"
CONF_MAX_EXPORT_POWER = "max_export_power"
CONF_MAX_CHARGE_CURRENT = "max_charge_current"
CONF_MAX_DISCHARGE_CURRENT = "max_discharge_current"
CONF_BASE_MODE = "base_mode"
CONF_MANAGE_CHARGE_CURRENT = "manage_charge_current"
CONF_CURRENT_DEADBAND = "current_deadband"
CONF_EXPORT_DEADBAND = "export_deadband"
CONF_VERIFY_EVERY = "verify_every"

TRANSPORT_SOLARMAN = "solarman_v5"
TRANSPORT_MODBUS = "modbus_tcp"
TRANSPORTS = [TRANSPORT_SOLARMAN, TRANSPORT_MODBUS]

DEFAULT_PORT = {TRANSPORT_SOLARMAN: 8899, TRANSPORT_MODBUS: 502}
DEFAULT_SCAN_INTERVAL = 30
DEFAULT_UNIT_ID = 1

DEFAULT_MAX_GRID_CHARGE_POWER = 9000
DEFAULT_MAX_EXPORT_POWER = 12000
DEFAULT_MAX_CHARGE_CURRENT = 185
DEFAULT_MAX_DISCHARGE_CURRENT = 185
DEFAULT_BASE_MODE = 2          # zero export to CT (external CT)
DEFAULT_MANAGE_CHARGE_CURRENT = False
DEFAULT_CURRENT_DEADBAND = 2   # A
DEFAULT_EXPORT_DEADBAND = 100  # W
DEFAULT_VERIFY_EVERY = 10      # cycles

MIN_SCAN_INTERVAL = 10
MAX_SCAN_INTERVAL = 300

CONFLICT_POLICIES = ["charge_priority", "export_priority", "net"]

# --------------------------------------------------------------------------
# Device
# --------------------------------------------------------------------------
MANUFACTURER = "Deye"
MODEL = "SUN-12K-SG05LP3-EU-SM2"

STORAGE_VERSION = 1
STORAGE_KEY = f"{DOMAIN}.{{entry_id}}.snapshot"

SERVICE_APPLY = "apply"
SERVICE_SNAPSHOT = "snapshot"
SERVICE_RESTORE = "restore"

ATTR_ENTRY_ID = "entry_id"

UPDATE_INTERVAL = timedelta(seconds=DEFAULT_SCAN_INTERVAL)
