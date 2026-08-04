# Host setup

## Packages used on Fedora (dev machine)

```bash
# already useful
pip install --user platformio esptool
sudo dnf install -y picocom minicom
# arduino-cli optional parallel toolchain
```

User must be in `dialout` to open `/dev/ttyUSB0`.

## PlatformIO

```bash
cd firmware/aim-controller      # or firmware/mpu-reader for raw values
pio run                          # build
pio run -t upload --upload-port /dev/ttyUSB0
pio device monitor -b 115200 --port /dev/ttyUSB0
```

## Bridge and range

```bash
pip install --user pyserial
python3 tools/aim_bridge.py --port /dev/ttyUSB0   # http://127.0.0.1:8000/
python3 tools/aim_bridge.py --simulate            # no hardware
python3 tools/aim_monitor.py --seconds 10         # rate / drift report
```

Only one program can hold the serial port. Stop the bridge before flashing.

## arduino-cli (optional)

```bash
arduino-cli core install esp8266:esp8266
arduino-cli board list
# FQBN: esp8266:esp8266:nodemcuv2
```

## Identify the stick

```bash
esptool --port /dev/ttyUSB0 chip-id
# expect ESP8266EX + MAC
```

## Troubleshooting I2C / MPU

| Symptom | Check |
|---------|--------|
| `none found` on scan | VCC≈3.3 V on MPU, GND common, jumpers in **same breadboard column** as pins |
| Found only when pins swapped | SDA/SCL reversed — use SDA→D2, SCL→D1 |
| Upload fails | Close serial monitor or bridge; confirm CH340 on `ttyUSB0` |
| Nano not listed | Need Mini‑USB data cable; won’t appear via ESP USB |
| Tools say the board is dead but it is streaming | Another sketch may be flashed — reflash `firmware/aim-controller` |
| Crosshair drifts | Press **R** to re-centre, or send `c` to recalibrate while still |
| Crosshair runs to one side, and re-centring only buys a minute | Bias captured while the gun was moving. Set it down for ~10 s and the tracker fixes it; re-centre to clear the yaw already banked. `# CAL` reports `wander` when this happened |
| Crosshair pinned to an edge | Aim offset is stale — re-centre, or raise sensitivity |
| One press fires twice | Raise `DEBOUNCE_MS` in the aim-controller firmware |
| Trigger never fires | Check the two button legs are **diagonal**, one to `D5`, one to `G` |
| Range page blank | Bridge not running, or another process owns `/dev/ttyUSB0` |
| Reload flick never fires | Flick faster — it needs ~200°/s down; magazine must not be full |
| Aim jumps after a fast swing | Gyro clipped. Check `clips=` in the `# PEAK` lines and widen `GYRO_FS_DPS` |
| Reload triggers while aiming | Lower the aim speed or raise `FLICK_DPS` in `web/range.js` |

## Choosing the gyro range

```bash
python3 tools/gyro_survey.py     # speaks the instructions aloud
```

It walks through resting, aiming, flicking and an all-out swing, then reports
which full-scale range fits. Set `GYRO_FS_DPS` in
`firmware/aim-controller/src/main.cpp` to the smallest value with about 2x
headroom and reflash.

Speech needs `espeak-ng` and a sink with non-zero volume:

```bash
sudo dnf install -y espeak-ng
pactl set-sink-volume @DEFAULT_SINK@ 55%
```

## Host-side tests

Everything that does not need hands on the gun runs from one script:

```bash
tools/run_tests.sh        # firmware, game and bridge
tools/run_tests.sh --all  # plus the browser and the live controller
```

| Suite | What it covers |
|---|---|
| `test_trigger.cpp` | Debounce, driven by bounce a finger cannot produce |
| `test_attitude.cpp` | Complementary filter, gyro bias, shake, yaw decay |
| `test_bias.cpp` | Runtime bias tracking: bad calibration, pans, thermal drift |
| `check_web.js` | Page and script agree on ids and classes |
| `test_range.js` | Round flow, ammo, reload, waves, timer |
| `test_bridge.py` | Serial parsing, through a pseudo-terminal |
| `range3d --selftest` | Reticle and raycast agree, centre and all corners |
| `visual_check.py` | Real browser renders, connects and plays |

The 3D range needs a virtual environment; the runner skips that suite rather
than failing when there isn't one. See `range3d/README.md`.

The two C++ suites run the firmware's own headers on the host. That is the only
way to reach the cases that actually break them — a switch chattering forty
times in three milliseconds, a gyro bias integrating for a minute, a press
spanning the `millis()` rollover — none of which can be staged by holding the
gun and hoping.

Both were checked by deliberately breaking the code to confirm the tests
notice. That step earned its keep: the first version of the trigger tests
passed with the debounce timer reset deleted, because shot counts cannot tell a
window that restarts from one that never does.

Two properties worth knowing as a player came out of this:

- **A trigger press shorter than 25 ms is discarded, not delayed.** Deliberate
  taps run 50 ms and up, so this only bites if the switch is failing.
- **Yaw compresses long turns.** See the yaw section in `PROTOCOL.md`.

`test_bridge.py` needs no hardware: `os.openpty()` gives it a real serial device
to feed truncated lines, binary noise and the wrong field count. That last case
is the bug that shipped on Aug 2 and went unnoticed until Aug 4.

The visual check needs the bridge running and Chromium installed:

```bash
pip install --user playwright && python3 -m playwright install chromium
```

It fails on any console error, on a canvas that never draws, on a round that
will not start, and on a controller that is not actually streaming, then saves
a screenshot to `/tmp/range.png`.

That last check matters: the page plays fine from the keyboard, so a board
running the wrong firmware looks identical to a healthy one. The check watches
the device clock and fails if it is frozen. Use `--no-device` when you only
want to test the page.

## Desktop screenshots on GNOME Wayland

`grim` needs a wlroots compositor and GNOME is not one, so it fails with
"compositor doesn't support the screen capture protocol". The old
`org.gnome.Shell.Screenshot` D-Bus method is refused with `AccessDenied`.
Neither is a bug — GNOME does not let arbitrary processes read the screen.

Go through the XDG portal instead:

```bash
flatpak permission-set screenshot screenshot '' yes   # grant once
python3 tools/screenshot.py --out /tmp/desktop.png
```

Revoke whenever you want:

```bash
flatpak permission-set screenshot screenshot '' no
```

Capturing the range page itself does not need any of this — `visual_check.py`
renders the page in its own browser.

## Serial monitor tip

```bash
picocom -b 115200 /dev/ttyUSB0
# exit: Ctrl-A then Ctrl-X
```
