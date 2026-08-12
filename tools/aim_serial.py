#!/usr/bin/env python3
"""Read and parse the gun controller's serial aim stream.

Reads `AIM,ms,pitch,yaw,roll,trigger[,shots]` lines from the NodeMCU.
Used by `range3d/main.py` and the host-side parser tests.

    python3 -c "from aim_serial import AimSource, read_serial"
"""

from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass, asdict


@dataclass
class AimState:
    pitch: float = 0.0
    yaw: float = 0.0
    roll: float = 0.0
    trigger: int = 0
    shots: int = 0
    device_ms: int = 0
    seq: int = 0
    connected: bool = False
    source: str = "none"
    # False while the device is running on a gyro bias it does not believe,
    # which is a broken aim rather than a broken connection.
    bias_ok: bool = True


class AimSource:
    """Latest-value store shared between the reader thread and the game."""

    def __init__(self) -> None:
        self._state = AimState()
        self._lock = threading.Lock()

    def set(self, **fields) -> None:
        with self._lock:
            for key, value in fields.items():
                setattr(self._state, key, value)
            self._state.seq += 1

    def snapshot(self) -> AimState:
        with self._lock:
            return AimState(**asdict(self._state))


def read_serial(source: AimSource, port: str, baud: int, reset: bool) -> None:
    import serial  # imported here so --simulate works without pyserial

    while True:
        try:
            with serial.Serial(port, baud, timeout=1) as ser:
                if reset:
                    ser.setDTR(False)
                    ser.setRTS(True)
                    time.sleep(0.1)
                    ser.setRTS(False)
                ser.reset_input_buffer()
                source.set(connected=True, source=port)
                print(f"[serial] reading {port} @ {baud}")

                while True:
                    raw = ser.readline().decode("utf-8", errors="replace").strip()
                    if not raw:
                        continue
                    if raw.startswith("#"):
                        print(f"[device] {raw}")
                        if "UNTRUSTED" in raw:
                            source.set(bias_ok=False)
                        elif "trusted=" in raw:
                            source.set(bias_ok="trusted=1" in raw)
                        elif "recovered" in raw:
                            source.set(bias_ok=True)
                        continue
                    if not raw.startswith("AIM,"):
                        continue
                    parts = raw.split(",")
                    # 6 fields is the pre-debounce firmware, 7 adds the counter.
                    if len(parts) not in (6, 7):
                        continue
                    try:
                        fields = dict(
                            device_ms=int(parts[1]),
                            pitch=float(parts[2]),
                            yaw=float(parts[3]),
                            roll=float(parts[4]),
                            trigger=int(parts[5]),
                        )
                        if len(parts) == 7:
                            fields["shots"] = int(parts[6])
                    except ValueError:
                        continue
                    source.set(**fields)
        except Exception as exc:  # keep running across unplug/replug
            source.set(connected=False, source="disconnected")
            print(f"[serial] error: {exc}; retrying in 2s")
            time.sleep(2)


def simulate(source: AimSource) -> None:
    print("[serial] simulating aim input")
    source.set(connected=True, source="simulated")
    start = time.time()
    while True:
        t = time.time() - start
        source.set(
            device_ms=int(t * 1000),
            pitch=12.0 * math.sin(t * 0.7),
            yaw=18.0 * math.sin(t * 0.45),
            roll=5.0 * math.sin(t * 0.3),
            trigger=int(t % 3 < 0.1),
            shots=int(t // 3),
        )
        time.sleep(0.01)
