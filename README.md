# Gyro Gunfight

Motion-aim drone shooting game — point a physical **ESP8266 NodeMCU + IMU gun** at the screen and shoot down quadcopters in a 3D test chamber.

**Repo:** https://github.com/priyanshuchawda/gyro-gunfight

---

## Status (2026-08-12)

| Piece | Status |
|-------|--------|
| 3D drone range (`range3d/`) | Working — Ursina, shadows, hit feedback, self-test |
| NodeMCU ESP8266EX over USB (CH340 `/dev/ttyUSB0`) | Working |
| MPU IMU on I2C `0x68` (SDA=`D2`, SCL=`D1`) | Working — accel / gyro / temp |
| Aim firmware (calibration + complementary filter) | Working — 100 Hz, ±1000 dps, no clipping |
| Runtime gyro bias tracking | Working — heals bad boot calibration while playing |
| Mid-swing calibration rejection | Working — refuses a bias measured while moving |
| Hardware trigger on `D5`, debounced | Working |
| Magnetometer (AK8963) | Not present on this module |
| OLED, I2C LCD, IR sensor, A4988 | In kit — not wired yet |
| Networked two-player match | Not started |

---

## Quick start — play the drone range

No hardware? Skip straight to simulate mode.

### 1. Install Python deps

```bash
cd ~/game
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python ursina pyserial numpy pillow
```

(`numpy` and `pillow` are only used by the self-test; the game runs without them.)

### 2. Run (no gun needed)

```bash
.venv/bin/python range3d/main.py --simulate
```

### 3. Run with the physical gun

Flash the aim controller, then:

```bash
cd firmware/aim-controller
pio run -t upload --upload-port /dev/ttyUSB0

cd ~/game
.venv/bin/python range3d/main.py --port /dev/ttyUSB0
```

Hold the gun still for a second after reset — that is the gyro calibration.

### Controls

| Action | Gun | Keyboard |
|--------|-----|----------|
| Fire | Trigger on `D5` | <kbd>Space</kbd> |
| Re-centre aim | — | <kbd>C</kbd> |
| Quit | — | <kbd>Esc</kbd> |

Quadcopters drift at varying depth. Shadows are the main distance cue. See [range3d/README.md](range3d/README.md) for lighting notes, hit feedback, and self-test details.

### Verify it works

```bash
.venv/bin/python range3d/main.py --simulate --selftest
tools/run_tests.sh    # firmware + serial parsing + 3D projection (needs .venv)
```

---

## Hardware

See [docs/HARDWARE.md](docs/HARDWARE.md) for the full kit inventory, pin map, and wiring.

### Wire (NodeMCU ↔ MPU)

| MPU | NodeMCU |
|-----|---------|
| VCC | **3V** |
| GND | **G** |
| SCL | **D1** (GPIO5) |
| SDA | **D2** (GPIO4) |

Trigger button: one leg to **D5** (GPIO14), the other to **G**. The firmware uses the internal pull-up — no external resistor.

### Tools

- [PlatformIO Core](https://platformio.org/) (`pio`) — flash firmware
- Python 3 + `pyserial` — serial aim input
- Serial debug: `picocom` / `minicom` @ **115200**

---

## Layout

| Path | What |
|------|------|
| [`range3d/`](range3d/) | **Main game** — 3D drone range (Ursina) |
| [`firmware/aim-controller/`](firmware/aim-controller/) | Filtered pitch/yaw/roll + trigger over serial |
| [`firmware/mpu-reader/`](firmware/mpu-reader/) | Raw IMU dump for bring-up |
| [`tools/aim_serial.py`](tools/aim_serial.py) | Serial aim parser (used by the 3D range) |
| [`tools/aim_monitor.py`](tools/aim_monitor.py) | Rate, noise, and drift report |
| [`tools/run_tests.sh`](tools/run_tests.sh) | Host-side test runner |
| [`docs/`](docs/) | Hardware, setup, protocol, roadmap |

---

## Docs

| Doc | Contents |
|-----|----------|
| [range3d/README.md](range3d/README.md) | Drone game design, lighting traps, self-test |
| [docs/HARDWARE.md](docs/HARDWARE.md) | Parts list, voltages, pinouts, wiring |
| [docs/SETUP.md](docs/SETUP.md) | Host tools, flash, serial, troubleshooting |
| [docs/PROTOCOL.md](docs/PROTOCOL.md) | Serial line format, bias tracking, commands |
| [docs/ROADMAP.md](docs/ROADMAP.md) | Milestones |

---

## License

MIT — see [LICENSE](LICENSE).
