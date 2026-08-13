# Gyro Gunfight

Point a physical **ESP8266 + IMU gun** at the screen and shoot spider webs at drones in a 3D test chamber. No gun? Keyboard simulate mode works too.

**Repo:** https://github.com/priyanshuchawda/gyro-gunfight

---

## Play in 3 steps (no hardware)

You only need a clone of this repo and Python 3.12+. You do **not** need extra asset packs or a separate “game directory”.

```bash
git clone https://github.com/priyanshuchawda/gyro-gunfight.git
cd gyro-gunfight

# once
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python ursina pyserial numpy pillow

# play
.venv/bin/python range3d/main.py --simulate
```

(`numpy` / `pillow` are only for the self-test; the game runs without them.)

### Controls

| Action | Keyboard | Physical gun |
|--------|----------|--------------|
| Fire web | <kbd>Space</kbd> | Trigger on `D5` |
| Re-centre aim | <kbd>C</kbd> | — |
| Settings | <kbd>S</kbd> or **SETTINGS** button | — |
| Quit / close settings | <kbd>Esc</kbd> | — |

### Settings

Open **SETTINGS** (bottom-right) or press <kbd>S</kbd>:

- **Theme** — Light or Dark (options stay readable in both)
- **Sensitivity** — `0.50x` … `2.00x` (higher = faster reticle)

Choices are saved to `range3d/settings.json` on your machine (not committed).

### Sound

Fire plays `range3d/sounds/shoot.mp3` (bundled with the game). Hits play `web_wrap.wav`. If OpenAL / audio is unavailable, shots still work — only the SFX is skipped.

---

## Play with the physical gun

```bash
cd firmware/aim-controller
pio run -t upload --upload-port /dev/ttyUSB0

cd ../..
.venv/bin/python range3d/main.py --port /dev/ttyUSB0
```

Hold the gun still for a second after reset (gyro calibration).

### Wire (NodeMCU ↔ MPU)

| MPU | NodeMCU |
|-----|---------|
| VCC | **3V** |
| GND | **G** |
| SCL | **D1** (GPIO5) |
| SDA | **D2** (GPIO4) |

Trigger: one leg to **D5** (GPIO14), the other to **G** (internal pull-up).

Full kit notes: [docs/HARDWARE.md](docs/HARDWARE.md) · flash / serial: [docs/SETUP.md](docs/SETUP.md)

---

## Status (2026-08-13)

| Piece | Status |
|-------|--------|
| 3D drone range (`range3d/`) | Working — webs, settings, light/dark, SFX, self-test |
| Aim firmware + runtime bias tracking | Working |
| Hardware trigger on `D5` | Working |
| Magnetometer | Not on this module |
| Networked multiplayer | Not started |

---

## Verify

```bash
.venv/bin/python range3d/main.py --simulate --selftest
tools/run_tests.sh
```

---

## What’s in the repo

| Path | What |
|------|------|
| [`range3d/`](range3d/) | **The game** (Ursina) + bundled sounds |
| [`firmware/aim-controller/`](firmware/aim-controller/) | Pitch/yaw/roll + trigger over serial |
| [`firmware/mpu-reader/`](firmware/mpu-reader/) | Raw IMU bring-up sketch |
| [`tools/`](tools/) | Serial parser, monitors, tests |
| [`docs/`](docs/) | Hardware, setup, protocol, roadmap |

Game design notes (lighting, projection self-test, web feedback): [range3d/README.md](range3d/README.md)

---

## License

MIT — see [LICENSE](LICENSE).
