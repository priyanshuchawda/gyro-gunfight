#!/usr/bin/env python3
"""Relay the gun controller's serial aim stream to the browser range.

Reads `AIM,ms,pitch,yaw,roll,trigger` lines from the NodeMCU and serves both
the static range page and a Server-Sent Events feed of the latest aim state.
Only the standard library plus pyserial is required.

    python3 tools/aim_bridge.py --port /dev/ttyUSB0
    python3 tools/aim_bridge.py --simulate      # no hardware needed
"""

from __future__ import annotations

import argparse
import json
import math
import threading
import time
from dataclasses import dataclass, asdict
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

WEB_ROOT = Path(__file__).resolve().parent.parent / "web"


@dataclass
class AimState:
    pitch: float = 0.0
    yaw: float = 0.0
    roll: float = 0.0
    trigger: int = 0
    device_ms: int = 0
    seq: int = 0
    connected: bool = False
    source: str = "none"


class AimSource:
    """Latest-value store shared between the reader thread and HTTP handlers."""

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
                print(f"[bridge] reading {port} @ {baud}")

                while True:
                    raw = ser.readline().decode("utf-8", errors="replace").strip()
                    if not raw:
                        continue
                    if raw.startswith("#"):
                        print(f"[device] {raw}")
                        continue
                    if not raw.startswith("AIM,"):
                        continue
                    parts = raw.split(",")
                    if len(parts) != 6:
                        continue
                    try:
                        source.set(
                            device_ms=int(parts[1]),
                            pitch=float(parts[2]),
                            yaw=float(parts[3]),
                            roll=float(parts[4]),
                            trigger=int(parts[5]),
                        )
                    except ValueError:
                        continue
        except Exception as exc:  # keep the page alive across unplug/replug
            source.set(connected=False, source="disconnected")
            print(f"[bridge] serial error: {exc}; retrying in 2s")
            time.sleep(2)


def simulate(source: AimSource) -> None:
    print("[bridge] simulating aim input")
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
        )
        time.sleep(0.01)


class RangeHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, source: AimSource, **kwargs):
        self.source = source
        super().__init__(*args, directory=str(WEB_ROOT), **kwargs)

    def do_GET(self):  # noqa: N802 - http.server API
        if self.path.startswith("/stream"):
            self.stream_aim()
        elif self.path.startswith("/aim"):
            self.send_json(asdict(self.source.snapshot()))
        else:
            super().do_GET()

    def send_json(self, payload: dict) -> None:
        body = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def stream_aim(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "keep-alive")
        self.end_headers()

        last_seq = -1
        try:
            while True:
                state = self.source.snapshot()
                # Trigger pulses are short, so never coalesce them away.
                if state.seq != last_seq or state.trigger:
                    last_seq = state.seq
                    payload = json.dumps(asdict(state))
                    self.wfile.write(f"data: {payload}\n\n".encode())
                    self.wfile.flush()
                time.sleep(1 / 120)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def log_message(self, *args):  # quiet the per-request noise
        pass


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", default="/dev/ttyUSB0", help="serial device")
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument("--http-port", type=int, default=8000)
    parser.add_argument("--simulate", action="store_true", help="fake aim input")
    parser.add_argument(
        "--no-reset",
        action="store_true",
        help="skip the DTR/RTS pulse that reboots the board on connect",
    )
    args = parser.parse_args()

    source = AimSource()
    if args.simulate:
        worker = threading.Thread(target=simulate, args=(source,), daemon=True)
    else:
        worker = threading.Thread(
            target=read_serial,
            args=(source, args.port, args.baud, not args.no_reset),
            daemon=True,
        )
    worker.start()

    handler = partial(RangeHandler, source=source)
    server = ThreadingHTTPServer(("127.0.0.1", args.http_port), handler)
    print(f"[bridge] range at http://127.0.0.1:{args.http_port}/")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[bridge] bye")


if __name__ == "__main__":
    main()
