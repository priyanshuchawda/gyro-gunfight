# Aim controller — ESP32 DevKit (Bluetooth LE)

Wireless drop-in for the wired NodeMCU aim stick. Same `AIM,...` protocol,
same attitude / bias / trigger code — streamed over **BLE Nordic UART**
instead of USB serial wires.

Advertises as **`GyroGun`**.

> This lives on the `esp32-bluetooth` branch. `main` still uses the USB
> NodeMCU firmware under `firmware/aim-controller/`.

## Wiring (ESP32 DevKit)

| MPU | ESP32 DevKit |
|-----|--------------|
| VCC | **3V3** |
| GND | **GND** |
| SCL | **GPIO22** |
| SDA | **GPIO21** |

| Trigger | ESP32 DevKit |
|---------|--------------|
| Leg A | **GPIO27** |
| Leg B | **GND** |

Power the board from USB only while flashing; once flashed, USB is optional
(debug mirror). Aim telemetry goes over Bluetooth.

## Flash

```bash
cd firmware/aim-controller-esp32-ble
pio run -t upload --upload-port /dev/ttyUSB0   # or ttyACM0
pio device monitor -b 115200
```

Hold the gun still for calibration after boot (same as the wired stick).

## Play

```bash
# once
uv pip install --python .venv/bin/python bleak

.venv/bin/python range3d/main.py --ble
# or pin a MAC after the first scan:
.venv/bin/python range3d/main.py --ble --ble-address AA:BB:CC:DD:EE:FF
```

Linux tip: your user needs Bluetooth access (`bluetooth` group / BlueZ).

## Protocol

Identical to [docs/PROTOCOL.md](../../docs/PROTOCOL.md):

```
AIM,<ms>,<pitch>,<yaw>,<roll>,<trigger>,<shots>
```

Host → device (BLE RX write or USB): `c` recalibrate, `z` zero yaw.

USB serial still prints every sample for debugging; BLE notifies ~100 Hz when
a client is connected.
