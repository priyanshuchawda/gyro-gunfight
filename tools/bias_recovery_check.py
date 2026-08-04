#!/usr/bin/env python3
"""Narrated check that a calibration taken mid-swing recovers by itself.

Reproduces the failure exactly as a player hits it: the board resets when the
port opens, so waving the gun during those first seconds is what poisons the
bias. Then it watches for the recovery, and finally measures how still a hand
can actually hold the gun -- which is the number the stillness threshold has to
be set against, and cannot be guessed from a desk.

    tools/bias_recovery_check.py

Speaks each instruction, because you cannot read a terminal while waving a gun
around with both hands.
"""
import argparse
import subprocess
import sys
import time

import serial


def say(text: str) -> None:
    print(f"\n>>> {text}")
    subprocess.Popen(["espeak-ng", "-s", "150", text],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", default="/dev/ttyUSB0")
    ap.add_argument("--baud", type=int, default=115200)
    args = ap.parse_args()

    say("Wave the gun around now. Keep waving until I say stop.")
    time.sleep(3)

    # The same DTR/RTS pulse the bridge uses, because rebooting the board is
    # what makes it recalibrate, and recalibrating mid-wave is the whole bug.
    ser = serial.Serial(args.port, args.baud, timeout=1)
    ser.setDTR(False)
    ser.setRTS(True)
    time.sleep(0.1)
    ser.setRTS(False)
    ser.reset_input_buffer()
    start = time.time()

    phases = [
        (0.0, "Keep waving.", None),
        (7.0, "Stop. Put the gun down on the desk and let go.", "settle"),
        (22.0, "Pick the gun up and hold it aimed at the monitor. Hold steady.",
         "aim"),
        (40.0, None, None),
    ]
    phase_i = 0
    current = None

    yaw_at = {}
    wander_by_phase = {"settle": [], "aim": []}
    snapped = None
    cal_line = ""

    while True:
        elapsed = time.time() - start
        if phase_i < len(phases) and elapsed >= phases[phase_i][0]:
            when, text, tag = phases[phase_i]
            if text:
                say(text)
            current = tag
            phase_i += 1
            if phase_i >= len(phases):
                break

        line = ser.readline().decode("utf-8", "replace").strip()
        if not line:
            continue

        if line.startswith("#"):
            if "CAL" in line:
                cal_line = line
                print(f"  {elapsed:5.1f}s  {line}")
            elif "recovered" in line:
                snapped = elapsed
                print(f"  {elapsed:5.1f}s  {line}")
            elif "BIAS" in line:
                print(f"  {elapsed:5.1f}s  {line}")
                if current in wander_by_phase:
                    for part in line.split():
                        if part.startswith("wander="):
                            wander_by_phase[current].append(
                                float(part.split("=")[1]))
            continue

        parts = line.split(",")
        if parts[0] == "AIM" and len(parts) >= 5:
            yaw_at[round(elapsed)] = float(parts[3])

    say("Done. You can put it down.")
    print("\n" + "=" * 60)
    print(cal_line or "(no calibration line seen)")
    if snapped is not None:
        print(f"recovered {snapped:.1f} s in, "
              f"{snapped - 7.0:.1f} s after the gun was set down")
    else:
        print("NO RECOVERY -- the tracker never found a still window")

    for tag, label in (("settle", "on the desk"), ("aim", "held and aimed")):
        vals = wander_by_phase[tag]
        if vals:
            print(f"gyro wander {label:15s} "
                  f"min {min(vals):.2f}  max {max(vals):.2f} dps")

    tail = [v for k, v in yaw_at.items() if k >= 34]
    if tail:
        print(f"yaw while aiming: min {min(tail):+.1f}  max {max(tail):+.1f} deg")
    return 0


if __name__ == "__main__":
    sys.exit(main())
