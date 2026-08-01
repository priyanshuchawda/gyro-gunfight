# Host setup

## Packages used on Fedora (dev machine)

```bash
# already useful
pip install --user platformio esptool
sudo dnf install -y picocom minicom
# arduino-cli optional parallel toolchain
```

User must be in `dialout` to open `/dev/ttyUSB0`.

## PlatformIO

```bash
cd firmware/aim-controller      # or firmware/mpu-reader for raw values
pio run                          # build
pio run -t upload --upload-port /dev/ttyUSB0
pio device monitor -b 115200 --port /dev/ttyUSB0
```

## Bridge and range

```bash
pip install --user pyserial
python3 tools/aim_bridge.py --port /dev/ttyUSB0   # http://127.0.0.1:8000/
python3 tools/aim_bridge.py --simulate            # no hardware
python3 tools/aim_monitor.py --seconds 10         # rate / drift report
```

Only one program can hold the serial port. Stop the bridge before flashing.

## arduino-cli (optional)

```bash
arduino-cli core install esp8266:esp8266
arduino-cli board list
# FQBN: esp8266:esp8266:nodemcuv2
```

## Identify the stick

```bash
esptool --port /dev/ttyUSB0 chip-id
# expect ESP8266EX + MAC
```

## Troubleshooting I2C / MPU

| Symptom | Check |
|---------|--------|
| `none found` on scan | VCC≈3.3 V on MPU, GND common, jumpers in **same breadboard column** as pins |
| Found only when pins swapped | SDA/SCL reversed — use SDA→D2, SCL→D1 |
| Upload fails | Close serial monitor or bridge; confirm CH340 on `ttyUSB0` |
| Nano not listed | Need Mini‑USB data cable; won’t appear via ESP USB |
| Crosshair drifts | Press **R** to re-centre, or send `c` to recalibrate while still |
| Crosshair pinned to an edge | Aim offset is stale — re-centre, or raise sensitivity |
| One press fires twice | Raise `DEBOUNCE_MS` in the aim-controller firmware |
| Trigger never fires | Check the two button legs are **diagonal**, one to `D5`, one to `G` |
| Range page blank | Bridge not running, or another process owns `/dev/ttyUSB0` |
| Reload flick never fires | Flick faster — it needs ~200°/s down; magazine must not be full |
| Aim jumps after a fast swing | Gyro clipped. Check `clips=` in the `# PEAK` lines and widen `GYRO_FS_DPS` |
| Reload triggers while aiming | Lower the aim speed or raise `FLICK_DPS` in `web/range.js` |

## Choosing the gyro range

```bash
python3 tools/gyro_survey.py     # speaks the instructions aloud
```

It walks through resting, aiming, flicking and an all-out swing, then reports
which full-scale range fits. Set `GYRO_FS_DPS` in
`firmware/aim-controller/src/main.cpp` to the smallest value with about 2x
headroom and reflash.

Speech needs `espeak-ng` and a sink with non-zero volume:

```bash
sudo dnf install -y espeak-ng
pactl set-sink-volume @DEFAULT_SINK@ 55%
```

## Host-side tests

```bash
node tools/check_web.js   # page and script agree on ids and classes
node tools/test_range.js  # round flow, ammo, reload, waves, timer
```

## Serial monitor tip

```bash
picocom -b 115200 /dev/ttyUSB0
# exit: Ctrl-A then Ctrl-X
```
