#!/usr/bin/env python3
"""Probe a Deye/Solarman dongle: plain Modbus TCP, or Solarman V5?

A Deye dongle usually listens on TCP 8899 and speaks *Solarman V5* — a vendor
framing wrapped around Modbus RTU.  Some newer sticks also answer plain Modbus
TCP (usually on 502, sometimes on 8899).  This script sends a bare Modbus TCP
"read holding registers" request and tells you what came back.

    python tools/probe_transport.py 192.168.1.50
    python tools/probe_transport.py 192.168.1.50 --ports 502 8899

It reads registers 587-588 (battery voltage and SOC) so a valid answer is easy
to recognise.  Nothing is written to the inverter.
"""

from __future__ import annotations

import argparse
import socket
import struct
import sys


def read_holding(host: str, port: int, unit: int = 1,
                 start: int = 587, count: int = 2, timeout: float = 3.0):
    """Return (registers, raw_bytes) or raise."""
    transaction_id = 0x0001
    pdu = struct.pack(">BHH", 0x03, start, count)
    mbap = struct.pack(">HHHB", transaction_id, 0, len(pdu) + 1, unit)

    with socket.create_connection((host, port), timeout=timeout) as sock:
        sock.settimeout(timeout)
        sock.sendall(mbap + pdu)
        data = sock.recv(512)

    if len(data) < 9:
        raise ValueError(f"short response ({len(data)} bytes): {data!r}")

    # MBAP(7) + function code + byte count + payload
    function = data[7]
    if function & 0x80:
        raise ValueError(f"Modbus exception {data[8]:#04x}")
    if function != 0x03:
        raise ValueError(f"unexpected function code {function:#04x}")

    byte_count = data[8]
    payload = data[9:9 + byte_count]
    if len(payload) != count * 2:
        raise ValueError(f"expected {count*2} data bytes, got {len(payload)}")

    registers = struct.unpack(f">{count}H", payload)
    return registers, data


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("host", help="IP address of the dongle logger")
    parser.add_argument("--ports", nargs="+", type=int, default=[8899, 502],
                        help="TCP ports to try (default: 8899 502)")
    parser.add_argument("--unit", type=int, default=1, help="Modbus slave id")
    args = parser.parse_args()

    print(f"probing {args.host} for plain Modbus TCP (FC03, registers 587-588)\n")
    any_ok = False

    for port in args.ports:
        try:
            registers, raw = read_holding(args.host, port, unit=args.unit)
        except (OSError, ValueError) as exc:
            print(f"  port {port}: no plain Modbus TCP  ({exc})")
            continue

        any_ok = True
        voltage = registers[0] / 100.0
        soc = registers[1]
        print(f"  port {port}: PLAIN MODBUS TCP WORKS")
        print(f"            raw        = {raw.hex(' ')}")
        print(f"            reg 587    = {registers[0]}  -> {voltage:.2f} V battery")
        print(f"            reg 588    = {registers[1]}  -> {soc} % SOC")
        print()
        if 30 <= voltage <= 70 and 0 <= soc <= 100:
            print("  -> looks like a real inverter. Use writer: \"modbus\" "
                  f"(hub host={args.host}, port={port}).")
        else:
            print("  -> valid Modbus answer, but the values look odd; check the unit id.")

    if not any_ok:
        print("\n  No plain Modbus TCP response.")
        print("  That is the normal result for the stock Solarman stick: it speaks")
        print("  Solarman V5 on 8899 (a vendor wrapper around Modbus RTU), which is")
        print("  what the Solarman HA integration uses. Keep writer: \"solarman\".")
        print("\n  (A timeout can also mean the dongle accepts only one connection;")
        print("   close the SolarMAN app / pause the integration and retry.)")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
