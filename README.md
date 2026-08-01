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
| Magnetometer (AK8963) | Not present / not responding on this module |
| Arduino Nano | On breadboard — needs Mini-USB to program |
| OLED, I2C LCD, IR sensor, A4988 | In kit — not wired yet |
| Game loop / multiplayer | Not started |

Sample live reading after flash:

```text
I2C scan: 0x68
WHO_AM_I=0x75 => MPU-family (clone)
A: -0.39  0.05  0.94 g | G: 0.1  -5.3  -0.3 dps | T: 31.1C | R/P: 3.2/22.5
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

## Quick start — read the IMU

### Tools
- [PlatformIO Core](https://platformio.org/) (`pio`)
- or `arduino-cli` with `esp8266:esp8266` core
- Serial: `picocom` / `minicom` @ **115200**

### Wire (NodeMCU ↔ MPU)

| MPU | NodeMCU |
|-----|---------|
| VCC | **3V** |
| GND | **G** |
| SCL | **D1** (GPIO5) |
| SDA | **D2** (GPIO4) |

### Flash & monitor

```bash
cd firmware/mpu-reader
pio run -t upload --upload-port /dev/ttyUSB0
pio device monitor -b 115200 --port /dev/ttyUSB0
# or: picocom -b 115200 /dev/ttyUSB0
```

Firmware lives in [`firmware/mpu-reader`](firmware/mpu-reader).

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
| [docs/ROADMAP.md](docs/ROADMAP.md) | Game milestones |

---

## License

MIT — see [LICENSE](LICENSE).
