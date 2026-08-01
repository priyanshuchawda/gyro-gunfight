# Hardware inventory

Everything currently in the Gyro Gunfight kit.

## Controllers

### NodeMCU ESP8266 (primary — connected)
| Field | Value |
|-------|--------|
| Chip | ESP8266EX |
| Features | Wi‑Fi, 160 MHz, 26 MHz crystal |
| Flash | 4 MB |
| MAC | `8c:4f:00:4b:80:33` |
| USB‑Serial | CH340 → `/dev/ttyUSB0` |
| Logic | **3.3 V** |

Useful pins for this project:

| Label | GPIO | Role |
|-------|------|------|
| D1 | 5 | I2C SCL (MPU) |
| D2 | 4 | I2C SDA (MPU) |
| D5 | 14 | Trigger button to GND (`INPUT_PULLUP`, active low) |
| D0, D3–D8 | various | free for IR / HUD / reload |
| 3V | — | sensor power |
| G | — | common ground |
| VIN / VU | — | 5 V from USB (do not feed into 3.3 V‑only pins) |

### Arduino Nano (on breadboard, not required yet)
| Field | Value |
|-------|--------|
| MCU | ATmega328P (typical clone) |
| Logic | **5 V** |
| Program port | **USB Mini‑B** (not USB‑C / full‑size B) |
| I2C | A4=SDA, A5=SCL |

Breadboard alone does **not** give upload access. Use Mini‑USB, USB‑TTL on RX/TX/GND/DTR, or ISP.

**Voltage warning:** Nano TX is 5 V. Do not wire directly into ESP RX without level shifting.

---

## Sensors & modules

| Module | Interface | Notes | Wired? |
|--------|-----------|-------|--------|
| Blue IMU (MPU‑family) | I2C `0x68` | WHO_AM_I `0x75` (clone). Accel + gyro + temp. No AK8963 mag. | **Yes** → ESP |
| 0.96″ OLED | I2C (usually `0x3C`) | HUD candidate | No |
| 16×2 LCD + I2C backpack | I2C | Alternate HUD | No |
| IR obstacle sensor | Digital (+ pot) | Trigger / hit detect | No |
| A4988‑style driver (purple) | STEP/DIR + motor PSU | Recoil / turret later — needs **separate VMOT** | No |
| Slide switch | Digital | Power / mode | No |

### MPU pinout (blue breakout)
`VCC · GND · SCL · SDA · EDA · ECL · AD0 · INT · NCS · FSYNC`

For basic use only connect **VCC, GND, SCL, SDA**.

---

## Confirmed wiring (working)

```
MPU VCC  →  NodeMCU 3V
MPU GND  →  NodeMCU G
MPU SCL  →  NodeMCU D1
MPU SDA  →  NodeMCU D2
```

Verified: I2C device at `0x68`, continuous accel/gyro stream @ 115200 baud,
100 Hz filtered aim output with ~0.2° yaw drift over 10 s.

Optional trigger (not yet soldered):

```
Button leg A → NodeMCU D5
Button leg B → NodeMCU G
```

---

## Power rules

1. Common **GND** across all modules that talk to each other.  
2. MPU and ESP logic at **3.3 V**.  
3. A4988 **VMOT** from a separate motor supply (not USB). Tie motor PSU GND to logic GND.  
4. Prefer powering the stick from NodeMCU USB while developing.

---

## Cables & extras

- Micro‑USB data cable (NodeMCU)
- Mini‑USB data cable (Nano) — charge‑only cables will fail uploads
- Dupont M‑M / M‑F / F‑F jumpers
