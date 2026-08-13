# Gyro Gunfight (`esp32-bluetooth` branch)

Point a physical **ESP32 DevKit + IMU gun** at the screen over **Bluetooth LE**
(no aim data cable). Optional **coin vibrator** buzzes on fire and hits.

**Repo:** https://github.com/priyanshuchawda/gyro-gunfight  
**Branch:** `esp32-bluetooth`

---

## Play in 3 steps (no hardware)

```bash
git clone https://github.com/priyanshuchawda/gyro-gunfight.git
cd gyro-gunfight
git checkout esp32-bluetooth

uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python ursina pyserial numpy pillow bleak

.venv/bin/python range3d/main.py --simulate
```

| Action | Keyboard | Gun |
|--------|----------|-----|
| Fire web | <kbd>Space</kbd> | Trigger **GPIO27** |
| Re-centre | <kbd>C</kbd> | — |
| Settings | <kbd>S</kbd> | — |
| Quit | <kbd>Esc</kbd> | — |

Settings: theme (light/dark) + aim sensitivity. Sound is bundled under
`range3d/sounds/`.

---

## ESP32 DevKit over Bluetooth

### Wire

| Part | ESP32 DevKit |
|------|--------------|
| MPU-6050 VCC / GND / SCL / SDA | **3V3 / GND / GPIO22 / GPIO21** (AD0→GND → `0x68`) |
| Trigger | **GPIO27** → GND |
| Coin vibrator | **GPIO26** via NPN/MOSFET (see firmware README) |

Full vibrator circuit: [firmware/aim-controller-esp32-ble/README.md](firmware/aim-controller-esp32-ble/README.md)

### Flash + play

```bash
cd firmware/aim-controller-esp32-ble
pio run -t upload --upload-port /dev/ttyUSB0

cd ../..
.venv/bin/python range3d/main.py --ble
```

Board advertises as **`GyroGun`**. Hold still ~1 s after boot for gyro cal.
Trigger buzzes locally; hits send a longer pulse over BLE.

USB debug mirror still works: `.venv/bin/python range3d/main.py --port /dev/ttyUSB0`

---

## Layout

| Path | What |
|------|------|
| [`range3d/`](range3d/) | 3D drone / web game |
| [`firmware/aim-controller-esp32-ble/`](firmware/aim-controller-esp32-ble/) | ESP32 DevKit BLE + haptics |
| [`firmware/aim-controller/`](firmware/aim-controller/) | Original NodeMCU USB stick |
| [`tools/aim_ble.py`](tools/aim_ble.py) | BLE reader + haptic writes |
| [`tools/aim_serial.py`](tools/aim_serial.py) | Shared AIM parser |
| [`docs/PROTOCOL.md`](docs/PROTOCOL.md) | AIM lines + `v` / `h` commands |

---

## License

MIT — see [LICENSE](LICENSE).
