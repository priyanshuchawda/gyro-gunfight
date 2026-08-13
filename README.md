# Gyro Gunfight (`esp32-bluetooth` branch)

Point a physical **ESP32 DevKit + IMU gun** at the screen over **Bluetooth LE**
(no aim wires to the PC). Wired NodeMCU serial still works on `main`.

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

### Controls

| Action | Keyboard | Gun |
|--------|----------|-----|
| Fire web | <kbd>Space</kbd> | Trigger (GPIO27) |
| Re-centre | <kbd>C</kbd> | — |
| Settings | <kbd>S</kbd> | — |
| Quit | <kbd>Esc</kbd> | — |

---

## ESP32 DevKit over Bluetooth

### Wire the stick

| MPU | ESP32 DevKit |
|-----|--------------|
| VCC | **3V3** |
| GND | **GND** |
| SCL | **GPIO22** |
| SDA | **GPIO21** |
| Trigger | **GPIO27** → GND |

### Flash firmware

```bash
cd firmware/aim-controller-esp32-ble
pio run -t upload --upload-port /dev/ttyUSB0
```

Board advertises as **`GyroGun`** (Nordic UART BLE service).

### Run the game

```bash
.venv/bin/python range3d/main.py --ble
```

Hold still one second after power-on for gyro calibration.

Details: [firmware/aim-controller-esp32-ble/README.md](firmware/aim-controller-esp32-ble/README.md)

### Still want USB serial?

```bash
.venv/bin/python range3d/main.py --port /dev/ttyUSB0
```

(The ESP32 firmware mirrors AIM lines on USB for debugging.)

---

## Layout

| Path | What |
|------|------|
| [`range3d/`](range3d/) | 3D drone range |
| [`firmware/aim-controller-esp32-ble/`](firmware/aim-controller-esp32-ble/) | **ESP32 DevKit BLE aim stick** |
| [`firmware/aim-controller/`](firmware/aim-controller/) | Original NodeMCU USB stick |
| [`tools/aim_ble.py`](tools/aim_ble.py) | BLE reader (bleak) |
| [`tools/aim_serial.py`](tools/aim_serial.py) | Shared AIM parser + USB reader |

---

## License

MIT — see [LICENSE](LICENSE).
