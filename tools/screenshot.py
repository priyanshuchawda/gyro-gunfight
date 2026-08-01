#!/usr/bin/env python3
"""Take a desktop screenshot through the XDG desktop portal.

GNOME on Wayland refuses direct screen capture, which is why `grim` and the
old `org.gnome.Shell.Screenshot` D-Bus call both fail. The portal is the
sanctioned route: it asks permission once, remembers the answer in the
permission store, and works without further prompting after that.

Grant it up front with:

    flatpak permission-set screenshot screenshot '' yes

    python3 tools/screenshot.py --out /tmp/desktop.png
"""

from __future__ import annotations

import argparse
import shutil
import sys
import urllib.parse

import gi

gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib  # noqa: E402

PORTAL_BUS = "org.freedesktop.portal.Desktop"
PORTAL_PATH = "/org/freedesktop/portal/desktop"


def take_screenshot(interactive: bool, timeout_s: float) -> str | None:
    bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    loop = GLib.MainLoop()
    result: dict[str, object] = {}

    # The reply arrives as a signal on a Request object, not as a return value.
    def on_response(_conn, _sender, _path, _iface, _signal, params):
        code, results = params.unpack()
        result["code"] = code
        result["uri"] = results.get("uri")
        loop.quit()

    subscription = bus.signal_subscribe(
        PORTAL_BUS,
        "org.freedesktop.portal.Request",
        "Response",
        None,
        None,
        Gio.DBusSignalFlags.NONE,
        on_response,
    )

    options = {
        "interactive": GLib.Variant("b", interactive),
        "handle_token": GLib.Variant("s", "gyro_gunfight_shot"),
    }

    bus.call_sync(
        PORTAL_BUS,
        PORTAL_PATH,
        "org.freedesktop.portal.Screenshot",
        "Screenshot",
        GLib.Variant("(sa{sv})", ("", options)),
        GLib.VariantType("(o)"),
        Gio.DBusCallFlags.NONE,
        -1,
        None,
    )

    GLib.timeout_add_seconds(int(timeout_s), lambda: (loop.quit(), False)[1])
    loop.run()
    bus.signal_unsubscribe(subscription)

    if result.get("code") != 0 or not result.get("uri"):
        return None
    return urllib.parse.unquote(urllib.parse.urlparse(str(result["uri"])).path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="/tmp/desktop.png")
    parser.add_argument(
        "--interactive",
        action="store_true",
        help="let the shell offer area or window selection",
    )
    parser.add_argument("--timeout", type=float, default=30)
    args = parser.parse_args()

    path = take_screenshot(args.interactive, args.timeout)
    if not path:
        print("screenshot denied or timed out", file=sys.stderr)
        print("grant it with: flatpak permission-set screenshot screenshot '' yes",
              file=sys.stderr)
        return 1

    if path != args.out:
        shutil.copyfile(path, args.out)
    print(args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
