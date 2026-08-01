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
cd firmware/mpu-reader
pio run                          # build
pio run -t upload --upload-port /dev/ttyUSB0
pio device monitor -b 115200 --port /dev/ttyUSB0
```

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
| Upload fails | Close serial monitor; confirm CH340 on `ttyUSB0` |
| Nano not listed | Need Mini‑USB data cable; won’t appear via ESP USB |

## Serial monitor tip

```bash
picocom -b 115200 /dev/ttyUSB0
# exit: Ctrl-A then Ctrl-X
```
