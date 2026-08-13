# Aim controller — ESP32 DevKit (Bluetooth LE)

Wireless aim stick for Gyro Gunfight. Same `AIM,...` protocol as the wired
NodeMCU build, streamed over **BLE Nordic UART** (advertises as **`GyroGun`**).
Includes a **phone-style coin vibrator** for fire/hit haptic feedback.

> Branch: `esp32-bluetooth`. `main` still uses USB NodeMCU under
> `firmware/aim-controller/`.

## Wiring (ESP32 DevKit)

### IMU + trigger (MPU-6050)

| Part | ESP32 DevKit |
|------|--------------|
| MPU-6050 VCC | **3V3** |
| MPU-6050 GND | **GND** |
| MPU-6050 SCL | **GPIO22** |
| MPU-6050 SDA | **GPIO21** |
| MPU-6050 AD0 | **GND** (I2C address `0x68`; tie to 3V3 for `0x69`) |
| Trigger button | **GPIO27** → **GND** (internal pull-up) |

Firmware expects **MPU-6050** (`WHO_AM_I == 0x68`). Accel/gyro FS and DLPF
match the 6050 register map; temperature uses the 6050 scale.

### Coin vibrator (pancake / mobile vibe motor)

Do **not** drive the motor straight from a GPIO — it draws more current than
the pin can safely supply. Use a small NPN (2N2222 / S8050) or N-MOSFET:

```
ESP32 GPIO26 ── 1 kΩ ──► NPN base
NPN emitter ────────────► GND
NPN collector ──────────► vibrator −
vibrator + ─────────────► 3V3
diode (1N4148) across motor, cathode to 3V3 (flyback)
```

| Part | Pin |
|------|-----|
| Vibe drive (transistor base via 1 kΩ) | **GPIO26** |
| Motor + | **3V3** |
| Motor − | transistor collector |
| Common | **GND** |

On boot the firmware pulses the motor once so you can confirm the wiring.

## Flash

```bash
cd firmware/aim-controller-esp32-ble
pio run -t upload --upload-port /dev/ttyUSB0   # or ttyACM0
pio device monitor -b 115200
```

Hold the gun still for calibration after reset.

## Play

```bash
uv pip install --python .venv/bin/python bleak
.venv/bin/python range3d/main.py --ble
# optional: .venv/bin/python range3d/main.py --ble --ble-address AA:BB:CC:DD:EE:FF
```

Linux: your user needs Bluetooth access (BlueZ / `bluetooth` group).

### What buzzes when

| Event | Source | Feel |
|-------|--------|------|
| Boot | firmware | short chirp |
| Trigger pull | firmware (`shots++`) | short fire pulse |
| Shot from game | host sends `v` | short fire pulse |
| Enemy hit | host sends `h` | longer hit pulse |

## Protocol

Same as [docs/PROTOCOL.md](../../docs/PROTOCOL.md):

```
AIM,<ms>,<pitch>,<yaw>,<roll>,<trigger>,<shots>
```

Host → device (BLE write or USB): `c` calibrate, `z` zero yaw, `v` fire vibe,
`h` hit vibe.

USB serial still mirrors every AIM line for debugging.
