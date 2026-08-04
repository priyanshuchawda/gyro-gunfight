# Aim protocol

The controller streams plain ASCII lines over USB serial at **115200 baud**.

## Telemetry

```
AIM,<device_ms>,<pitch>,<yaw>,<roll>,<trigger>,<shots>
```

| Field | Type | Meaning |
|-------|------|---------|
| `device_ms` | int | `millis()` since boot, for rate and latency checks |
| `pitch` | float° | Nose up/down, fused accel + gyro |
| `yaw` | float° | Left/right, gyro-integrated and re-centred over time |
| `roll` | float° | Barrel twist, fused accel + gyro |
| `trigger` | 0/1 | Debounced `D5` (GPIO14) level |
| `shots` | int | Debounced presses since boot, monotonic |

Count shots from the **delta of `shots`**, not from a `0 -> 1` edge on
`trigger`. The counter survives a dropped serial line; an edge does not. A
decrease means the board rebooted, so resynchronise rather than firing.

Lines starting with `#` are human-readable logs (boot banner, calibration
results, errors) and can be shown or ignored.

Measured on hardware: **100 Hz**, noise ≈0.03°, yaw drift ≈0.2° over 10 s.

### What yaw actually reports

Pitch and roll are anchored to gravity, so they mean what they say. Yaw has no
compass to anchor it, and the 0.995 per-sample decay that stops it drifting
also stops it integrating honestly. Two consequences fall out of that, both
pinned by `test_attitude.cpp`:

- A half-second swing at 90 dps reports **39.7°, not the ideal 45°**. The decay
  eats roughly an eighth of every swing at that length.
- A *sustained* turn saturates at **1.99° per dps of turn rate**, so holding
  90 dps stops at 179° and holding 30 dps stops at 59.7°, however far you
  actually turn. Past about a second, yaw describes how fast you are turning
  rather than how far you have turned.

Neither is a bug to fix; without a magnetometer the choice is between a
crosshair that wanders off screen and one that under-reports long turns. It
matters for game design: aiming should be built around short flicks, which the
filter reports faithfully, rather than long sweeps, which it compresses.

## Commands (host → device)

| Byte | Effect |
|------|--------|
| `c` | Re-run gyro bias calibration — hold the gun still |
| `z` | Zero the yaw axis |

## Diagnostics

Once a second the controller also emits:

```
# PEAK gx=<dps> gy=<dps> gz=<dps> clips=<count>
```

`clips` counts samples that hit the gyro's full-scale rail, where the real
rotation rate was larger than the sensor could report. It should stay at zero;
anything else means motion is being lost. `tools/gyro_survey.py` uses these
lines to pick the right range.

## Filtering notes

- Gyro bias is averaged over 400 samples at boot; the gun must be still.
- A complementary filter (`alpha = 0.98`) trusts the gyro short-term and the
  accelerometer long-term for pitch and roll.
- Yaw has no absolute reference because this IMU has no working
  magnetometer, so it decays gently back toward centre instead of walking off.
- The gyro runs at ±1000 dps full scale. Measured play peaks at 336 dps, so
  ±250 (the power-on default) clips outright and ±500 leaves only 1.5x
  headroom. The costs are lopsided: a wider range only coarsens counts a
  little, while a clipped swing is unrecoverable in yaw with no compass.
- The deadzone is fixed at 8 raw counts rather than a hardcoded dps figure, so
  it tracks resolution automatically if the range changes. At ±1000 that works
  out to 0.244 dps, well below any deliberate aim movement.
- The trigger must hold a new level for 25 ms before it counts, which rejects
  the contact chatter that otherwise shows up as ~18 ms phantom presses.

## Bridge JSON

`tools/aim_bridge.py` republishes the same state as JSON on `/aim` and as a
Server-Sent Events feed on `/stream`:

```json
{"pitch": 12.4, "yaw": -3.1, "roll": 0.8, "trigger": 0, "shots": 7,
 "device_ms": 48120, "seq": 4812, "connected": true, "source": "/dev/ttyUSB0"}
```

`seq` increments per update so clients can detect stalls. The bridge also
accepts the older 6-field line and simply leaves `shots` at 0.
