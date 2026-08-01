#!/usr/bin/env python3
"""Load the range in a real browser and verify it actually renders and plays.

The headless rule tests in `test_range.js` never touch a browser, so they
cannot catch a broken layout, a canvas that stays blank, or a script that dies
on load. This drives the real page: it fails on any console error, checks the
canvas is drawing rather than empty, plays a few shots through the keyboard
path, and saves a screenshot to look at.

    python3 tools/visual_check.py                     # needs the bridge running
    python3 tools/visual_check.py --shot /tmp/x.png
"""

from __future__ import annotations

import argparse
import sys

DEFAULT_URL = "http://127.0.0.1:8000/"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--shot", default="/tmp/range.png")
    parser.add_argument("--width", type=int, default=1440)
    parser.add_argument("--height", type=int, default=900)
    args = parser.parse_args()

    from playwright.sync_api import sync_playwright

    problems: list[str] = []

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": args.width, "height": args.height})

        page.on("console", lambda m: problems.append(f"console {m.type}: {m.text}")
                if m.type == "error" else None)
        page.on("pageerror", lambda e: problems.append(f"page error: {e}"))

        page.goto(args.url, wait_until="load")
        page.wait_for_timeout(2500)  # let the SSE feed arrive and frames draw

        # A canvas that never draws still has a size, so compare pixels.
        blank = page.evaluate(
            """() => {
                const c = document.getElementById('range');
                const ctx = c.getContext('2d');
                const d = ctx.getImageData(0, 0, c.width, c.height).data;
                for (let i = 3; i < d.length; i += 4) if (d[i] !== 0) return false;
                return true;
            }"""
        )
        if blank:
            problems.append("canvas is completely empty - nothing is being drawn")

        link = page.text_content("#link") or ""
        rate = page.text_content("#rate") or ""
        state_before = page.evaluate("() => game.state")

        # Space starts the round, then fires; check the game responds.
        page.keyboard.press("Space")
        page.wait_for_timeout(300)
        state_after = page.evaluate("() => game.state")
        if state_after != "playing":
            problems.append(f"trigger did not start a round (state={state_after})")

        targets = page.evaluate("() => targets.length")
        if targets == 0:
            problems.append("round started but no targets spawned")

        for _ in range(3):
            page.keyboard.press("Space")
            page.wait_for_timeout(150)

        shots = page.evaluate("() => game.shots")
        ammo = page.evaluate("() => game.ammo")
        if shots == 0:
            problems.append("firing did not register any shots")
        if ammo == 6:
            problems.append("firing did not consume ammo")

        page.wait_for_timeout(400)
        page.screenshot(path=args.shot)
        browser.close()

    print(f"bridge link : {link}")
    print(f"stream rate : {rate}")
    print(f"state       : {state_before} -> {state_after}")
    print(f"targets     : {targets}")
    print(f"shots/ammo  : {shots} fired, {ammo} left")
    print(f"screenshot  : {args.shot}")

    if problems:
        print("\nFAIL")
        for problem in problems:
            print(f"  {problem}")
        return 1

    print("\nPASS - page renders, connects, and plays")
    return 0


if __name__ == "__main__":
    sys.exit(main())
