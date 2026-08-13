#!/usr/bin/env python3
"""Read the ESP32 DevKit aim stream over Bluetooth Low Energy (NUS).

Same `AIM,...` lines as USB serial. The board advertises as `GyroGun` and
exposes the Nordic UART Service. Host→device writes carry calibrate / haptic
bytes (`c`, `z`, `v`, `h`).

    .venv/bin/python range3d/main.py --ble
"""

from __future__ import annotations

import asyncio
import threading
import time

from aim_serial import AimSource, apply_device_line, parse_aim_line

NUS_TX = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"  # notify: device → host
NUS_RX = "6e400002-b5a3-f393-e0a9-e50e24dcca9e"  # write: host → device
DEFAULT_NAME = "GyroGun"


def read_ble(source: AimSource, name: str = DEFAULT_NAME,
             address: str | None = None) -> None:
    """Blocking reader for a worker thread — runs an asyncio BLE loop."""
    try:
        import bleak  # noqa: F401
    except ImportError:
        source.set(connected=False, source="ble-missing")
        print("[ble] install bleak:  uv pip install --python .venv/bin/python bleak")
        while True:
            time.sleep(60)

    while True:
        try:
            asyncio.run(_session(source, name=name, address=address))
        except Exception as exc:
            source.set(connected=False, source="disconnected")
            print(f"[ble] error: {exc}; retrying in 2s")
            time.sleep(2)


async def _session(source: AimSource, name: str,
                   address: str | None) -> None:
    from bleak import BleakClient, BleakScanner

    target = address
    label = address or name
    if not target:
        print(f"[ble] scanning for {name!r}…")
        device = await BleakScanner.find_device_by_name(name, timeout=20.0)
        if device is None:
            raise RuntimeError(f"no BLE device named {name!r}")
        target = device.address
        label = f"{device.name} ({device.address})"

    buffer = ""

    def on_notify(_handle: int, data: bytearray) -> None:
        nonlocal buffer
        buffer += data.decode("utf-8", errors="replace")
        while "\n" in buffer or "\r" in buffer:
            if "\n" in buffer:
                raw, _, buffer = buffer.partition("\n")
            else:
                raw, _, buffer = buffer.partition("\r")
            buffer = buffer.lstrip("\r\n")
            line = raw.strip()
            if not line:
                continue
            if line.startswith("#"):
                print(f"[device] {line}")
                apply_device_line(source, line)
                continue
            fields = parse_aim_line(line)
            if fields:
                source.set(**fields)

    print(f"[ble] connecting to {label}")
    async with BleakClient(target, timeout=20.0) as client:
        source.set(connected=True, source=f"ble:{label}")
        print(f"[ble] connected {label}")
        await client.start_notify(NUS_TX, on_notify)
        try:
            while client.is_connected:
                for command in source.drain_commands():
                    try:
                        await client.write_gatt_char(
                            NUS_RX, command.encode("ascii"), response=False,
                        )
                    except Exception as exc:
                        print(f"[ble] write failed: {exc}")
                await asyncio.sleep(0.02)
        finally:
            try:
                await client.stop_notify(NUS_TX)
            except Exception:
                pass
    source.set(connected=False, source="disconnected")
    print("[ble] disconnected")


def read_ble_thread(source: AimSource, name: str = DEFAULT_NAME,
                    address: str | None = None) -> threading.Thread:
    thread = threading.Thread(
        target=read_ble, args=(source, name, address), daemon=True,
    )
    thread.start()
    return thread
