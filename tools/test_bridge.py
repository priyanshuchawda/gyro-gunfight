#!/usr/bin/env python3
"""Tests for the bridge's serial parsing, driven through a pseudo-terminal.

    python3 tools/test_bridge.py

os.openpty() hands back a real serial device the kernel is happy to open, so
the bridge can be fed bytes no real board would send: half a line, a stray
newline mid-packet, negative angles, a field count that changed under it. That
last one is the bug that shipped on Aug 2 and was not noticed until Aug 4.
"""
from __future__ import annotations

import contextlib
import io
import os
import pty
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from aim_bridge import AimSource, read_serial  # noqa: E402

failures = 0


def check(name: str, got, want) -> None:
    global failures
    if got == want:
        print(f"  ok    {name:<46} {got}")
    else:
        print(f"  FAIL  {name:<46} got {got!r}, want {want!r}")
        failures += 1


class FakeBoard:
    """A pseudo-terminal the bridge reads as if it were the NodeMCU."""

    def __init__(self) -> None:
        self.master, slave = pty.openpty()
        self.port = os.ttyname(slave)
        self.source = AimSource()
        self.thread = threading.Thread(
            target=read_serial,
            args=(self.source, self.port, 115200, False),
            daemon=True,
        )
        self.thread.start()
        time.sleep(0.4)  # let the reader open the port

    def send(self, text: str) -> None:
        os.write(self.master, text.encode())
        time.sleep(0.25)  # let the reader drain it

    def state(self):
        return self.source.snapshot()


def main() -> int:
    print("bridge serial parsing, driven through a pseudo-terminal\n")

    board = FakeBoard()
    check("opens the port and reports connected", board.state().connected, True)

    board.send("AIM,1000,10.5,-20.25,3.0,0,7\n")
    s = board.state()
    check("parses a 7 field packet: pitch", s.pitch, 10.5)
    check("parses a 7 field packet: negative yaw", s.yaw, -20.25)
    check("parses a 7 field packet: shots", s.shots, 7)
    check("parses a 7 field packet: device clock", s.device_ms, 1000)

    # The regression that shipped: a tool assumed 6 fields, firmware sent 7.
    board.send("AIM,2000,1.0,2.0,3.0,1\n")
    s = board.state()
    check("still accepts the older 6 field packet", s.pitch, 1.0)
    check("6 field packet leaves the old shot count", s.shots, 7)

    # Banner lines must not be parsed as telemetry, and must still reach the
    # console: watching for "# CAL done" is how you know the gun finished
    # calibrating. Dropping the echo is otherwise invisible, because the
    # "AIM," guard rejects these lines anyway.
    before = board.state()
    captured = io.StringIO()
    with contextlib.redirect_stdout(captured):
        board.send("# CAL done bias=0.1,0.2,0.3 samples=400\n")
    check("banner lines change nothing", board.state().pitch, before.pitch)
    check("banner lines are echoed to the console",
          "# CAL done" in captured.getvalue(), True)

    for junk in (
        "AIM,3000,not_a_number,2.0,3.0,0,9\n",
        "AIM,3000,1.0\n",
        "AIM\n",
        "GARBAGE,1,2,3,4,5,6\n",
        "AIM,3000,1.0,2.0,3.0,0,9,10,11,12\n",
        "\x00\xff\xfe binary noise \x01\n",
        "\n\n\n",
    ):
        board.send(junk)
    s = board.state()
    check("malformed packets are all ignored", (s.pitch, s.shots), (1.0, 7))

    # A packet split across reads, which happens whenever the USB buffer
    # boundary lands mid-line.
    os.write(board.master, b"AIM,4000,42.5,")
    time.sleep(0.25)
    board.send("11.0,12.0,1,99\n")
    s = board.state()
    check("reassembles a packet split mid-line", s.pitch, 42.5)
    check("reassembled packet carries its shots", s.shots, 99)

    # Values the firmware genuinely produces at the extremes.
    board.send("AIM,5000,-89.99,179.10,-170.0,1,100\n")
    s = board.state()
    check("accepts a saturated yaw", s.yaw, 179.10)
    check("accepts a steep negative pitch", s.pitch, -89.99)

    # seq is what the page uses to notice the stream is alive.
    a = board.state().seq
    board.send("AIM,6000,1.0,1.0,1.0,0,101\n")
    check("sequence advances on every good packet", board.state().seq > a, True)

    b = board.state().seq
    board.send("AIM,rubbish\n")
    check("sequence does not advance on a bad packet",
          board.state().seq, b)

    print(f"\n{'FAILURES' if failures else 'all bridge checks passed'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
