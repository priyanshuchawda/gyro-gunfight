#!/usr/bin/env python3
"""Print aim stream health: sample rate, range of motion, and drift.

    python3 tools/aim_monitor.py --seconds 10
"""

from __future__ import annotations

import argparse
import statistics
import time


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", default="/dev/ttyUSB0")
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument("--seconds", type=float, default=10.0)
    parser.add_argument("--no-reset", action="store_true")
    args = parser.parse_args()

    import serial

    with serial.Serial(args.port, args.baud, timeout=0.5) as ser:
        if not args.no_reset:
            ser.setDTR(False)
            ser.setRTS(True)
            time.sleep(0.1)
            ser.setRTS(False)
        ser.reset_input_buffer()

        samples: list[tuple[int, float, float, float, int]] = []
        seen = 0
        rejected = 0
        deadline = time.time() + args.seconds
        while time.time() < deadline:
            line = ser.readline().decode("utf-8", errors="replace").strip()
            if line.startswith("#"):
                print(line)
            elif line.startswith("AIM,"):
                seen += 1
                parts = line.split(",")
                # 6 fields is the pre-debounce firmware, 7 adds the shot counter.
                if len(parts) not in (6, 7):
                    rejected += 1
                    continue
                try:
                    samples.append(
                        (
                            int(parts[1]),
                            float(parts[2]),
                            float(parts[3]),
                            float(parts[4]),
                            int(parts[5]),
                        )
                    )
                except ValueError:
                    rejected += 1

    if not samples:
        if seen:
            # Blaming the firmware here would send you debugging the wrong layer.
            print(f"{seen} AIM lines arrived but none parsed ({rejected} rejected).")
            print("The board is streaming; this tool does not understand the format.")
        else:
            print("no AIM lines at all - is the aim-controller firmware flashed?")
        return

    if rejected:
        print(f"warning: {rejected} of {seen} AIM lines could not be parsed")

    span = (samples[-1][0] - samples[0][0]) / 1000.0
    print(f"\nsamples={len(samples)} duration={span:.1f}s rate={len(samples)/max(span, 1e-3):.1f} Hz")
    for index, name in ((1, "pitch"), (2, "yaw"), (3, "roll")):
        values = [s[index] for s in samples]
        settled = values[: min(100, len(values))]
        print(
            f"{name:6s} first={values[0]:8.2f} last={values[-1]:8.2f} "
            f"drift={values[-1] - values[0]:+7.2f} "
            f"min={min(values):8.2f} max={max(values):8.2f} "
            f"noise_sd={statistics.pstdev(settled):.3f}"
        )
    print("trigger pressed during run:", any(s[4] for s in samples))


if __name__ == "__main__":
    main()
