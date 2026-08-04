#!/usr/bin/env python3
"""Measure where yaw parks itself while the gun is not being moved.

With the decay in the firmware, a steady gyro bias does not walk yaw away
without bound; it settles at roughly `bias * 50`. That makes the resting yaw a
direct readout of the residual bias after calibration, which is otherwise
invisible from outside the device.

    tools/yaw_drift.py            # reset the board, so it recalibrates first
    tools/yaw_drift.py --no-reset # measure the bias the board is already using
"""
import argparse
import sys
import time

import serial

SETTLE_TAU_SAMPLES = 50.0  # yaw_eq / this = bias in dps, see AttitudeFilter


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", default="/dev/ttyUSB0")
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--seconds", type=float, default=60.0)
    ap.add_argument("--no-reset", action="store_true",
                    help="leave DTR/RTS alone, keeping the board's current bias")
    args = ap.parse_args()

    ser = serial.Serial()
    ser.port = args.port
    ser.baudrate = args.baud
    ser.timeout = 1.0
    if args.no_reset:
        ser.dtr = False
        ser.rts = False
    ser.open()
    time.sleep(0.3)
    ser.reset_input_buffer()

    print(f"hold the gun still for {args.seconds:.0f} s\n")
    start = time.time()
    samples = []
    while time.time() - start < args.seconds:
        line = ser.readline().decode("utf-8", "replace").strip()
        if not line:
            continue
        if line.startswith("#"):
            if "CAL" in line or "ERROR" in line:
                print(f"  {line}")
            continue
        parts = line.split(",")
        if parts[0] != "AIM" or len(parts) < 5:
            continue
        try:
            samples.append((time.time() - start, float(parts[2]),
                            float(parts[3]), float(parts[4])))
        except ValueError:
            continue

    if len(samples) < 50:
        print(f"only {len(samples)} samples, is the gun streaming?")
        return 1

    print(f"\n{len(samples)} samples over {samples[-1][0]:.1f} s\n")
    print(f"{'window':>12}  {'pitch':>8}  {'yaw':>8}  {'roll':>8}")
    span = samples[-1][0] / 6
    for i in range(6):
        lo, hi = i * span, (i + 1) * span
        chunk = [s for s in samples if lo <= s[0] < hi]
        if not chunk:
            continue
        n = len(chunk)
        print(f"{lo:5.0f}-{hi:3.0f} s  "
              f"{sum(c[1] for c in chunk)/n:8.2f}  "
              f"{sum(c[2] for c in chunk)/n:8.2f}  "
              f"{sum(c[3] for c in chunk)/n:8.2f}")

    tail = [s for s in samples if s[0] > samples[-1][0] * 0.7]
    resting = sum(s[2] for s in tail) / len(tail)
    print(f"\nyaw is resting at {resting:+.1f} deg")
    print(f"implied residual gyro bias {resting / SETTLE_TAU_SAMPLES:+.3f} dps")
    print(f"that is {abs(resting) / 70 * 100:.0f}% of a 70 deg screen, "
          f"{'off screen' if abs(resting) > 35 else 'on screen'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
