# Gyro Gunfight

Motion-aim gunfight game built around an **ESP8266 NodeMCU** + **IMU** controller.  
Tilt/aim with the gyro/accel stick; more peripherals (IR, OLED, stepper, Nano) are in the kit for future gameplay features.

**Repo:** https://github.com/priyanshuchawda/gyro-gunfight  
*(formerly `priyanshuchawda/in`)*

---

## Status (2026-08-02)

| Piece | Status |
|-------|--------|
| NodeMCU ESP8266EX over USB (CH340 `/dev/ttyUSB0`) | Working |
| MPU IMU on I2C `0x68` (SDA=`D2`, SCL=`D1`) | Working — accel / gyro / temp |
| Aim firmware (calibration + complementary filter) | Working — 100 Hz, ~0.2°/10 s drift |
| Serial → browser bridge | Working |
| Browser shooting range with live crosshair | Working |
| Hardware trigger on `D5`, debounced | Working — 7 presses, 7 shots, no double-fires |
| Magnetometer (AK8963) | Not present / not responding on this module |
| Arduino Nano | On breadboard — needs Mini-USB to program |
| OLED, I2C LCD, IR sensor, A4988 | In kit — not wired yet |
| Networked two-player match | Not started |

Measured stream from the controller:

```text
# imu ok @0x68
# CAL done bias=0.157,-5.554,-0.482 samples=400
AIM,14225,65.87,-2.47,5.46,0,7
samples=986 duration=9.9s rate=100.1 Hz
pitch drift +0.01°   yaw drift +0.21°   noise_sd 0.025°
```

---

## Hardware kit

See [docs/HARDWARE.md](docs/HARDWARE.md) for the full inventory, pin map, and wiring.

### Active now
- **NodeMCU ESP8266** (ESP8266EX, 4 MB flash, MAC `8c:4f:00:4b:80:33`)
- **MPU‑family IMU** (blue breakout, labeled like MPU‑9250; WHO_AM_I `0x75`, accel+gyro only)

### Also on hand
- Arduino Nano (Mini‑USB)
- 0.96″ OLED, 16×2 LCD + I2C backpack
- IR obstacle sensor
- A4988‑style stepper driver (purple)
- Dupont jumpers, slide switch, USB cable

---

## Quick start — play the range

### Tools
- [PlatformIO Core](https://platformio.org/) (`pio`)
- Python 3 with `pyserial`
- Serial fallback: `picocom` / `minicom` @ **115200**

### Wire (NodeMCU ↔ MPU)

| MPU | NodeMCU |
|-----|---------|
| VCC | **3V** |
| GND | **G** |
| SCL | **D1** (GPIO5) |
| SDA | **D2** (GPIO4) |

Trigger button: two **diagonal** legs, one to **D5** (GPIO14), the other to
**G**. No resistor — the firmware uses the internal pull-up.

### 1. Flash the aim controller

```bash
cd firmware/aim-controller
pio run -t upload --upload-port /dev/ttyUSB0
```

Hold the gun still for a second after reset — that is the gyro calibration.

### 2. Run the bridge and open the range

```bash
python3 tools/aim_bridge.py --port /dev/ttyUSB0
# then open http://127.0.0.1:8000/
```

No hardware nearby? `python3 tools/aim_bridge.py --simulate`.

Press **R** (or the button in the sidebar) to re-centre the crosshair,
**Space**/click to fire, and tune sensitivity and smoothing live.

### 3. Check stream health

```bash
python3 tools/aim_monitor.py --seconds 10
```

### Layout

| Path | What |
|------|------|
| [`firmware/aim-controller`](firmware/aim-controller) | Filtered pitch/yaw/roll + trigger over serial |
| [`firmware/mpu-reader`](firmware/mpu-reader) | Raw IMU dump, useful for bring-up and debugging |
| [`tools/aim_bridge.py`](tools/aim_bridge.py) | Serial → HTTP/SSE bridge, serves the range |
| [`tools/aim_monitor.py`](tools/aim_monitor.py) | Rate, noise, and drift report |
| [`web/`](web) | Browser shooting range |

---

## Project direction

Gunfight-style game where the breadboard stick is a **motion controller**:

1. **Aim** — pitch/roll (and later filtered gyro) from the MPU  
2. **Trigger / hit** — buttons, IR, or networked events  
3. **Feedback** — OLED / LCD HUD, sound, LEDs  
4. **Link** — Wi‑Fi (ESP8266) for arena / dual-player

Arduino Nano can stay as a co-processor later (motors, A4988, extra IO). Program it over **Mini‑USB** (not USB‑C/B); sharing a breadboard with the ESP does **not** replace Nano USB for uploads.

---

## Docs

| Doc | Contents |
|-----|----------|
| [docs/HARDWARE.md](docs/HARDWARE.md) | Parts list, voltages, pinouts, wiring rules |
| [docs/SETUP.md](docs/SETUP.md) | Host tools, flash, serial, troubleshooting |
| [docs/PROTOCOL.md](docs/PROTOCOL.md) | Serial line format, commands, bridge JSON |
| [docs/ROADMAP.md](docs/ROADMAP.md) | Game milestones |

---

## License

MIT — see [LICENSE](LICENSE).
