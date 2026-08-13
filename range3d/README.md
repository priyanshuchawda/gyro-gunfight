# 3D range

Spider-web drone range in a test chamber. Aim with the physical gyro gun, or
`--simulate` with the keyboard. The game lives entirely under `range3d/` plus
the shared serial helper in `tools/aim_serial.py` — clone the repo and run; no
separate asset download is required.

```bash
git clone https://github.com/priyanshuchawda/gyro-gunfight.git
cd gyro-gunfight
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python ursina pyserial numpy pillow

.venv/bin/python range3d/main.py --simulate   # no hardware
.venv/bin/python range3d/main.py              # live gun on /dev/ttyUSB0
```

| Key | Action |
|-----|--------|
| <kbd>Space</kbd> | Fire |
| <kbd>C</kbd> | Re-centre aim |
| <kbd>S</kbd> | Open / close **Settings** |
| <kbd>Esc</kbd> | Close settings, or quit |

## Settings

**SETTINGS** (corner button) or <kbd>S</kbd>:

- **Theme** — Light (white chamber) or Dark (night bay)
- **Sensitivity** — `0.50x`–`2.00x`; higher moves the reticle farther per degree

Prefs write to `range3d/settings.json` locally. Panel controls stay above the
dimmer overlay so labels and buttons remain readable in **both** themes.

On the `esp32-bluetooth` branch, fire/hit also pulse a coin vibrator on the
ESP32 DevKit stick when running with `--ble` (see the firmware README).

## Sound

| Event | File |
|-------|------|
| Fire | `sounds/shoot.mp3` (bundled) |
| Hit wrap | `sounds/web_wrap.wav` |

Playback uses Ursina/`Audio`. If the clip or OpenAL is missing, the shot still
registers; only the sound is skipped. Fallbacks (in order): `sounds/shoot.mp3`,
`sounds/shoot.wav`, `../web/sounds/shoot.mp3`, `sounds/web_thwip.wav`.

## What a shot does

A strand flies from below the eye to the impact. A hit wraps the drone in a
web, floats the score, flashes reticle ticks, and tumbles the wreck. A miss
leaves a web splat on the wall or block. Corner brackets appear when a drone is
under the reticle.

## Lighting traps (Ursina)

- Assign `sun.color` **after** constructing `DirectionalLight` — the constructor
  argument is ignored and full white clips this room.
- Override `shadow_color`; the stock value makes every shadow cyan.
- Hide the room shells from the shadow camera (`hide(0b0001)`) so side walls do
  not throw a slab across the back wall.

## Why light-gun, not FPS

The camera stays fixed; the gun steers a reticle. Yaw is dead-reckoned without a
magnetometer — fine on a crosshair you can re-centre, disorienting if it moved
the whole world.

## Serial

`range3d/main.py` imports `tools/aim_serial.py` and opens the port itself (one
less process). Shared parser means `tools/test_serial.py` covers this path too.

## Self-test

```bash
.venv/bin/python range3d/main.py --simulate --selftest
```

Places targets on the aim ray, fires, and checks hits — including a render
read-back so projection cannot agree with itself while disagreeing with the
screen. See the history of the aspect-ratio FOV bug in older commits for why
that check exists.

`--frames N --shot out.png` saves the window framebuffer. Add `--demo` to auto
aim and fire (misses every fourth shot on purpose).
