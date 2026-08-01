# MPU reader firmware

PlatformIO project for **NodeMCU v2 (ESP8266)** that:

1. Scans I2C
2. Wakes the MPU at `0x68`
3. Streams accel (g), gyro (°/s), temperature, and roll/pitch

## Pins
- SDA → `D2` (GPIO4)
- SCL → `D1` (GPIO5)

## Build / upload
```bash
pio run -t upload --upload-port /dev/ttyUSB0
pio device monitor -b 115200 --port /dev/ttyUSB0
```
