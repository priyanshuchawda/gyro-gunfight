#!/usr/bin/env python3
"""Measure how much gyro range real play actually uses.

The controller reports `# PEAK ... clips=N` once a second. This walks through
a set of motions, records the peak rate of each, and reports which full-scale
range fits with headroom. Use it before changing `GYRO_FS_DPS` in the
firmware — the right range is the smallest one that never clips, since wider
ranges cost resolution.

Instructions are spoken aloud when espeak-ng is present, so the person holding
the gun does not need to watch the screen.

    python3 tools/gyro_survey.py
    python3 tools/gyro_survey.py --quiet     # print prompts instead of speaking
"""

from __future__ import annotations

import argparse
import re
import shutil
import statistics
import subprocess
import time

PEAK_RE = re.compile(r"# PEAK gx=([\d.]+) gy=([\d.]+) gz=([\d.]+) dps clips=(\d+)")
AIM_RE = re.compile(r"AIM,(\d+),([-\d.]+),([-\d.]+),([-\d.]+),")
FULL_SCALES = (250, 500, 1000, 2000)

STAGES = (
    ("normal aiming", "Stage two. Aim at the screen normally, with small smooth movements.", 10),
    ("fast flicks", "Stage three. Fast flicks. Snap the gun between imaginary targets as fast as you would in a game.", 10),
    ("reload flicks", "Stage four. Reload flicks. Flick the barrel sharply downward about five times.", 9),
    ("worst case", "Stage five, the last one. Whip the gun as fast as you physically can.", 8),
)


class Voice:
    def __init__(self, enabled: bool) -> None:
        self.cmd = shutil.which("espeak-ng") if enabled else None

    def __call__(self, text: str) -> None:
        print(f"  >> {text}", flush=True)
        if self.cmd:
            subprocess.run([self.cmd, "-s", "150", "-a", "200", text], check=False)


def collect(ser, seconds: float):
    """Return (peak per axis, angle samples, clipped sample count)."""
    peaks, angles = [], []
    first = last = None
    deadline = time.time() + seconds
    while time.time() < deadline:
        line = ser.readline().decode("utf-8", errors="replace").strip()
        peak = PEAK_RE.match(line)
        if peak:
            peaks.append(tuple(float(peak[i]) for i in (1, 2, 3)))
            count = int(peak[4])
            if first is None:
                first = count
            last = count
            continue
        aim = AIM_RE.match(line)
        if aim:
            angles.append(tuple(float(v) for v in aim.groups()))
    axes = tuple(max((p[i] for p in peaks), default=0.0) for i in range(3))
    return axes, angles, (last or 0) - (first or 0)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", default="/dev/ttyUSB0")
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument("--quiet", action="store_true", help="do not speak prompts")
    args = parser.parse_args()

    import serial

    say = Voice(not args.quiet)
    results: dict[str, tuple[tuple[float, float, float], int]] = {}

    with serial.Serial(args.port, args.baud, timeout=0.5) as ser:
        ser.reset_input_buffer()

        say("Gyro survey. Stage one. Put the gun flat down and let go of it completely.")
        time.sleep(1.5)
        ser.reset_input_buffer()
        ser.write(b"c")  # recalibrate bias while it is genuinely still
        deadline = time.time() + 8
        while time.time() < deadline:
            line = ser.readline().decode("utf-8", errors="replace").strip()
            if "CAL done" in line:
                print(f"  {line}")
                break

        say("Leave it alone.")
        axes, angles, clips = collect(ser, 8)
        results["still"] = (axes, clips)
        if len(angles) > 50:
            noise = ", ".join(
                f"{name}={statistics.pstdev([a[i] for a in angles]):.4f}"
                for i, name in ((1, "pitch"), (2, "yaw"), (3, "roll"))
            )
            print(f"  angle noise sd: {noise}")
        say("Stage one done. Pick up the gun.")

        for key, prompt, seconds in STAGES:
            say(prompt)
            say("Three. Two. One. Go.")
            ser.reset_input_buffer()
            axes, _, clips = collect(ser, seconds)
            results[key] = (axes, clips)
            print(f"  {key}: peak {max(axes):.1f} dps, clips {clips}")
            say("Stop.")

        say("Survey complete.")

    print("\n" + "=" * 68)
    print(f"{'stage':16s} {'roll ax':>10s} {'pitch ax':>10s} {'yaw ax':>10s} {'MAX':>9s}  clips")
    print("=" * 68)
    worst = 0.0
    for key, (axes, clips) in results.items():
        peak = max(axes)
        if key != "still":
            worst = max(worst, peak)
        print(f"{key:16s} {axes[0]:10.1f} {axes[1]:10.1f} {axes[2]:10.1f} {peak:9.1f}  {clips}")

    still_peak = max(results["still"][0])
    verdict = "valid" if still_peak < 10 else "SUSPECT - was the gun really still?"
    print(f"\nstationary baseline peak {still_peak:.2f} dps ({verdict})")
    print(f"worst moving rate {worst:.1f} dps\n")

    for full_scale in FULL_SCALES:
        if worst >= full_scale:
            note = "CLIPS"
        else:
            note = f"{full_scale / worst:.2f}x headroom, {full_scale / 32768:.4f} dps/count"
        print(f"  +-{full_scale:5d} dps  {note}")

    usable = [f for f in FULL_SCALES if worst and f / worst >= 2.0]
    if usable:
        print(f"\nsuggested GYRO_FS_DPS: {usable[0]} (smallest with 2x headroom)")


if __name__ == "__main__":
    main()
