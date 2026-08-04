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
compass, so it is gyro-integrated and bled slowly back to centre.

That decay used to be **0.995 per sample**, which cost 39% of the aim offset
every second. Holding on a target near the screen edge meant watching the
crosshair slide out from under you, and no sensitivity setting could
compensate. It also compressed real movement: a half-second 90 dps swing came
back as 39.7° instead of 45°, and sustained turns saturated at 1.99° per dps,
so past a second yaw described how *fast* you were turning rather than how far.

Measuring with the decay switched off entirely showed real drift after
calibration is **0.31°/min** — a severe aiming penalty bought for a quarter of
a degree. It is now **0.9998**, and the behaviour pinned by `test_attitude.cpp`
is:

| | 0.995 (old) | 0.9998 (now) |
|---|---|---|
| Aim offset kept after 3 s | 22% | 94% |
| A 0.5 s, 90 dps swing | 39.7° | 44.8° |
| Sustained turn ceiling | 1.99°/dps | 50°/dps |
| Bias just past the deadzone settles at | 0.4° | 14.6° |

The measured 0.005 dps residual never reaches the integrator at all: the
0.244° deadzone removes it outright, so it is the deadzone rather than the
decay that handles real drift. The decay only bounds what leaks past.

The last row is the price, and it is steeper than it looks. **Yaw settles at
roughly fifty times the residual bias**, so an error of 0.7 dps — a fraction of
what picking the gun up during calibration produces — parks the crosshair off
the side of a 70° screen. Re-centring does not save you: it moves the software
offset while the bias underneath keeps pushing yaw back to the same place
within a minute.

Boot calibration alone was not a good enough foundation for a 50× multiplier,
so the bias is now tracked continuously while you play; see
[Runtime bias tracking](#runtime-bias-tracking) below.

## Commands (host → device)

| Byte | Effect |
|------|--------|
| `c` | Re-run gyro bias calibration — hold the gun still |
| `z` | Zero the yaw axis |

## Runtime bias tracking

The gyro bias is re-estimated while you play, so a bad boot calibration heals
itself instead of ruining the session. Whenever the gun is demonstrably
stationary, whatever the gyro reads at that moment *is* the bias, and the
estimate is eased toward it. The same mechanism absorbs thermal drift, which no
boot-time measurement can predict.

Stillness is judged from how much the raw gyro **varies**, never from how large
the bias-corrected rate is. That distinction is the whole design: a stationary
gyro reads a constant, and if the current estimate is wrong then the corrected
rate is large exactly when the correction is most needed, so a threshold on it
would lock the tracker out of ever fixing itself.

Two traps are worth knowing if you touch this:

- Check the accelerometer **per axis**, not its magnitude. Rotating the gun
  swings gravity from one axis to another while its length stays at exactly
  1 g, so a magnitude check reads a steady tilting pan as perfectly stationary
  and eats the player's own movement as bias.
- A perfectly constant *yaw* pan is unobservable in principle — yawing a level
  gun does not move gravity at all. Real hands are not that smooth, which the
  gyro spread check catches, and a slew limit of 0.6 dps/s caps what the
  undetectable case can cost before the gun is held still again.

Behaviour pinned by `test_bias.cpp`: a 1.5 dps calibration error is recovered
within about 6 s of holding steady, a swing or a hand-held pan does not move the
estimate at all, and five minutes of thermal drift is tracked to within 0.2 dps.

### Trusted and untrusted estimates

Slow easing is right for a bias that is nearly correct and wrong for one that
is nowhere near it. A calibration taken mid-swing measured **-27 dps** on Z;
easing away from that at the slew limit would need three quarters of a minute
of unbroken stillness, which is not a recovery. Measured: after ten full
seconds of perfect stillness, easing had only reached -21.6.

So calibration now judges itself. If the gyro wandered more than 3 dps while
measuring, the result is refused and retried, up to four times. If none are
clean the best attempt is kept but marked **untrusted**, and the first
genuinely still window then replaces it outright rather than easing toward it.
Yaw is zeroed at the same moment, because everything integrated under a bias
that turned out to be wrong is not an aim offset worth keeping. Once replaced,
the estimate is trusted and goes back to the slow path — a later pan can never
snap it.

### What stillness costs in practice

Measured on the board, gyro wander over the 0.6 s window:

| | wander |
|---|---|
| Resting on the desk | 0.24 – 0.34 dps |
| Held in hand, aiming at the screen | 24 – 175 dps |

The threshold is 2 dps, so the desk clears it with room to spare and a held gun
does not come close. **Recovery means putting the gun down, not holding it
steady** — a hand is roughly a hundred times too noisy, and no threshold that
accepted a hand would still reject aiming.

Accumulated yaw is a separate matter. On the snap path it is zeroed for you.
Otherwise, fixing the bias only stops *new* error; yaw already banked bleeds off
at 2%/s, so press `c` in the game to re-centre immediately.

### Why connecting no longer reboots the board

The bridge used to pulse DTR/RTS on connect, which reboots the ESP8266 and
makes it recalibrate. That put the one measurement the whole aim depends on at
the exact moment the player is picking the gun up — and yaw multiplies its
error by fifty. It was the direct cause of "the aim runs off to the left every
time I start the game".

Reset is now opt-in behind `--reset`. A calibration taken once at power-on, with
the gun on the desk, survives every launch after it.

## Diagnostics

Once a second the controller also emits:

```
# PEAK gx=<dps> gy=<dps> gz=<dps> clips=<count>
```

`clips` counts samples that hit the gyro's full-scale rail, where the real
rotation rate was larger than the sensor could report. It should stay at zero;
anything else means motion is being lost. `tools/gyro_survey.py` uses these
lines to pick the right range.

Every five seconds it reports the live bias estimate:

```
# BIAS 0.046,-5.436,-0.364 still=1 trusted=1 wander=0.27
```

`still=1` means the tracker believes the gun is stationary and is adjusting the
estimate; `trusted=0` means it is running on a calibration it does not believe
and is waiting for a still window to replace it. `wander` is the largest gyro
spread across the window, and is what the stillness threshold is compared
against. On a desk this board reads Z near `-0.39` with 0.04 dps of movement,
comfortably inside the 0.244 dps deadzone.

Calibration reports how far the gyro moved while it was measuring, and refuses
a measurement it cannot believe:

```
# CAL attempt 1 saw 220.0 dps of movement, retrying - put the gun down
# CAL UNTRUSTED after 4 attempts, best wander 200.5 dps
# BIAS recovered 0.007,-5.799,-0.224 - yaw re-centred
```

The recovery line is emitted once, when an untrusted estimate is replaced.

Two host-side tools read this from outside the firmware:
`tools/yaw_drift.py` turns resting yaw back into an implied bias, and
`tools/bias_recovery_check.py` narrates the whole failure and recovery aloud —
you cannot read a terminal while waving a gun around with both hands.

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
