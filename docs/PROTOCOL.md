# Aim protocol

The controller streams plain ASCII lines over USB serial at **115200 baud**.

## Telemetry

```
AIM,<device_ms>,<pitch>,<yaw>,<roll>,<trigger>
```

| Field | Type | Meaning |
|-------|------|---------|
| `device_ms` | int | `millis()` since boot, for rate and latency checks |
| `pitch` | float° | Nose up/down, fused accel + gyro |
| `yaw` | float° | Left/right, gyro-integrated and re-centred over time |
| `roll` | float° | Barrel twist, fused accel + gyro |
| `trigger` | 0/1 | `D5` (GPIO14) pulled to GND |

Lines starting with `#` are human-readable logs (boot banner, calibration
results, errors) and can be shown or ignored.

Measured on hardware: **100 Hz**, noise ≈0.03°, yaw drift ≈0.2° over 10 s.

## Commands (host → device)

| Byte | Effect |
|------|--------|
| `c` | Re-run gyro bias calibration — hold the gun still |
| `z` | Zero the yaw axis |

## Filtering notes

- Gyro bias is averaged over 400 samples at boot; the gun must be still.
- A complementary filter (`alpha = 0.98`) trusts the gyro short-term and the
  accelerometer long-term for pitch and roll.
- Yaw has no absolute reference because this IMU has no working
  magnetometer, so it decays gently back toward centre instead of walking off.
- A 0.06 dps deadzone stops sensor noise from creeping the aim.

## Bridge JSON

`tools/aim_bridge.py` republishes the same state as JSON on `/aim` and as a
Server-Sent Events feed on `/stream`:

```json
{"pitch": 12.4, "yaw": -3.1, "roll": 0.8, "trigger": 0,
 "device_ms": 48120, "seq": 4812, "connected": true, "source": "/dev/ttyUSB0"}
```

`seq` increments per update so clients can detect stalls.
