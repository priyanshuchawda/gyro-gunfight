#include <Arduino.h>
#include <Wire.h>
#include <math.h>

#include "attitude.h"
#include "bias.h"
#include "trigger.h"

// NodeMCU I2C
static const int PIN_SDA = 4;  // D2
static const int PIN_SCL = 5;  // D1
// Trigger button to GND (optional, may be unwired)
static const int PIN_TRIGGER = 14;  // D5

static const uint8_t MPU_ADDR = 0x68;

static const float DEG = 57.2957795f;
static const float ACC_LSB = 16384.0f;  // +-2 g

// Full-scale gyro range in dps: 250, 500, 1000 or 2000. Measured play peaks at
// 336 dps, so +-250 clips outright and +-500 leaves only 1.5x headroom. The
// costs are lopsided: coarser counts only widen the deadzone slightly, while a
// clipped swing is unrecoverable in yaw with no compass to correct it.
#define GYRO_FS_DPS 1000

#if GYRO_FS_DPS == 250
static const uint8_t GYRO_FS_SEL = 0x00;
static const float GYRO_LSB = 131.0f;
#elif GYRO_FS_DPS == 500
static const uint8_t GYRO_FS_SEL = 0x08;
static const float GYRO_LSB = 65.5f;
#elif GYRO_FS_DPS == 1000
static const uint8_t GYRO_FS_SEL = 0x10;
static const float GYRO_LSB = 32.8f;
#elif GYRO_FS_DPS == 2000
static const uint8_t GYRO_FS_SEL = 0x18;
static const float GYRO_LSB = 16.4f;
#else
#error "GYRO_FS_DPS must be 250, 500, 1000 or 2000"
#endif

// A raw count this close to full scale means the rate was clipped, not measured.
static const int16_t GYRO_CLIP_RAW = 32000;

// Accel is trusted slowly so hand shake does not fight the gyro.
static const float COMP_ALPHA = 0.98f;
// Yaw has no absolute reference (no magnetometer), so bleed it back to
// centre instead of letting residual bias walk the crosshair off screen.
// Yaw has no absolute reference without a magnetometer, so it is bled back to
// centre to stop residual gyro bias walking the crosshair off screen.
//
// This was 0.995, which cost 39% of the aim offset every second: hold on a
// target near the edge and the crosshair slides out from under you, which no
// amount of sensitivity tuning can fix. Measured with the decay disabled
// entirely, real drift after calibration is only 0.31 deg/min, so that was a
// severe aiming penalty bought for a quarter of a degree.
//
// At 0.9998 the offset loses 2% per second, which is imperceptible while
// tracking a target, and a steady bias settles at rate * 50 rather than
// growing without bound -- 0.26 deg at the measured drift. The catch is that
// it now leans on calibration being good, so hold the gun still at boot.
static const float YAW_DECAY = 0.9998f;
// Held at a fixed number of raw counts so the deadzone tracks resolution
// instead of silently vanishing when the full-scale range widens.
static const float GYRO_DEADZONE = 8.0f / GYRO_LSB;

static const uint16_t SAMPLE_HZ = 100;
static const uint16_t SAMPLE_US = 1000000UL / SAMPLE_HZ;

// Tactile switches chatter for a few ms on both make and break; a press has to
// stay put this long before it counts as real.
static const uint32_t DEBOUNCE_MS = 25;

// Runtime bias tracking. Boot calibration is a single measurement that assumes
// the gun is motionless for its duration, and the decay above multiplies any
// error in it by fifty, so being picked up during those samples is enough to
// park the crosshair off the side of the screen -- and re-centring will not
// help, because it moves the offset without touching the bias underneath.
// These are the values the host tests characterise; see test/test_bias.cpp.
static const uint16_t BIAS_WINDOW = 60;       // 0.6 s at 100 Hz
static const float BIAS_RATE_SPREAD = 2.0f;   // dps of wander still called still
static const float BIAS_ACC_SPREAD = 0.04f;   // g, per axis
static const float BIAS_GAIN = 0.004f;        // of the error, per sample
static const float BIAS_MAX_SLEW = 0.6f;      // dps per second, hard ceiling

// Same implementation the host tests drive; see test/test_attitude.cpp.
static AttitudeFilter attitude(COMP_ALPHA, YAW_DECAY, GYRO_DEADZONE);
static BiasTracker bias_tracker(BIAS_WINDOW, BIAS_RATE_SPREAD, BIAS_ACC_SPREAD,
                                BIAS_GAIN, BIAS_MAX_SLEW);
static uint32_t bias_report_ms = 0;
static uint32_t last_us = 0;
static bool calibrated = false;

static uint32_t gyro_clips = 0;     // samples that hit the full-scale rail
static Vec3 gyro_peak = {0, 0, 0};  // largest |rate| seen since the last report
static uint32_t peak_report_ms = 0;

// Same implementation the host tests drive; see test/test_trigger.cpp.
static TriggerDebouncer trigger(DEBOUNCE_MS);

static uint8_t writeReg(uint8_t reg, uint8_t val) {
  Wire.beginTransmission(MPU_ADDR);
  Wire.write(reg);
  Wire.write(val);
  return Wire.endTransmission();
}

static bool readBytes(uint8_t reg, uint8_t *buf, uint8_t n) {
  Wire.beginTransmission(MPU_ADDR);
  Wire.write(reg);
  if (Wire.endTransmission(false) != 0) return false;
  if (Wire.requestFrom((int)MPU_ADDR, (int)n) != n) return false;
  for (uint8_t i = 0; i < n; i++) buf[i] = Wire.read();
  return true;
}

static int16_t be16(uint8_t hi, uint8_t lo) {
  return (int16_t)((hi << 8) | lo);
}

static bool readImu(Vec3 &acc, Vec3 &rot, float &temp_c) {
  uint8_t raw[14];
  if (!readBytes(0x3B, raw, 14)) return false;
  acc.x = be16(raw[0], raw[1]) / ACC_LSB;
  acc.y = be16(raw[2], raw[3]) / ACC_LSB;
  acc.z = be16(raw[4], raw[5]) / ACC_LSB;
  temp_c = be16(raw[6], raw[7]) / 333.87f + 21.0f;

  int16_t rx = be16(raw[8], raw[9]);
  int16_t ry = be16(raw[10], raw[11]);
  int16_t rz = be16(raw[12], raw[13]);
  if (abs(rx) >= GYRO_CLIP_RAW || abs(ry) >= GYRO_CLIP_RAW ||
      abs(rz) >= GYRO_CLIP_RAW) {
    gyro_clips++;
  }

  rot.x = rx / GYRO_LSB;
  rot.y = ry / GYRO_LSB;
  rot.z = rz / GYRO_LSB;
  return true;
}

static bool imuBegin() {
  writeReg(0x6B, 0x80);  // reset
  delay(100);
  writeReg(0x6B, 0x00);  // wake
  delay(50);
  writeReg(0x6B, 0x01);  // gyro X clock
  writeReg(0x1A, 0x03);         // DLPF 44 Hz
  writeReg(0x19, 0x00);         // 1 kHz sample
  writeReg(0x1B, GYRO_FS_SEL);  // gyro full scale
  writeReg(0x1C, 0x00);         // accel +-2 g
  delay(50);

  Wire.beginTransmission(MPU_ADDR);
  return Wire.endTransmission() == 0;
}

// A calibration that wandered further than this was not a measurement of bias,
// it was a measurement of the player picking the gun up.
static const float CAL_MAX_WANDER = 3.0f;
static const uint8_t CAL_ATTEMPTS = 4;

// Returns the wandering seen, or -1 if the IMU gave nothing.
static float measureBias(uint16_t samples, Vec3 &out) {
  Vec3 sum = {0, 0, 0};
  Vec3 lo = {1e9f, 1e9f, 1e9f}, hi = {-1e9f, -1e9f, -1e9f};
  Vec3 acc, rot;
  float t;
  uint16_t got = 0;
  for (uint16_t i = 0; i < samples; i++) {
    if (readImu(acc, rot, t)) {
      sum.x += rot.x;
      sum.y += rot.y;
      sum.z += rot.z;
      lo.x = min(lo.x, rot.x); hi.x = max(hi.x, rot.x);
      lo.y = min(lo.y, rot.y); hi.y = max(hi.y, rot.y);
      lo.z = min(lo.z, rot.z); hi.z = max(hi.z, rot.z);
      got++;
    }
    delay(3);
  }
  if (got == 0) return -1.0f;
  out.x = sum.x / got;
  out.y = sum.y / got;
  out.z = sum.z / got;
  return max(max(hi.x - lo.x, hi.y - lo.y), hi.z - lo.z);
}

static void calibrate(uint16_t samples = 400) {
  Serial.println("# CAL start - hold the gun still");

  Vec3 best = {0, 0, 0};
  float best_wander = 1e9f;
  bool clean = false;

  for (uint8_t attempt = 1; attempt <= CAL_ATTEMPTS && !clean; attempt++) {
    Vec3 measured;
    const float wander = measureBias(samples, measured);
    if (wander < 0) {
      Serial.println("# CAL failed - no IMU data");
      return;
    }
    if (wander < best_wander) {
      best_wander = wander;
      best = measured;
    }
    clean = wander <= CAL_MAX_WANDER;
    if (!clean) {
      Serial.printf("# CAL attempt %u saw %.1f dps of movement, retrying - "
                    "put the gun down\n", attempt, wander);
    }
  }

  // Refusing a bad measurement rather than warning about it and using it
  // anyway. A calibration taken mid-swing was reading tens of dps of bias,
  // and yaw multiplies that by fifty.
  Vec3 acc, rot;
  float t;
  bias_tracker.seed(best, clean);
  if (readImu(acc, rot, t)) attitude.seed(acc);
  calibrated = true;
  last_us = micros();

  if (clean) {
    Serial.printf("# CAL done bias=%.3f,%.3f,%.3f wander=%.2f\n", best.x,
                  best.y, best.z, best_wander);
  } else {
    Serial.printf("# CAL UNTRUSTED after %u attempts, best wander %.1f dps - "
                  "hold the gun still for a second and it will fix itself\n",
                  CAL_ATTEMPTS, best_wander);
  }
}

// Runs every loop rather than every sample so a quick tap between IMU reads
// still lands inside the debounce window.
static void pollTrigger() {
  trigger.update(digitalRead(PIN_TRIGGER) == LOW, millis());
}

void setup() {
  Serial.begin(115200);
  delay(400);
  pinMode(PIN_TRIGGER, INPUT_PULLUP);

  Wire.begin(PIN_SDA, PIN_SCL);
  Wire.setClock(400000);

  Serial.println();
  Serial.println("# gyro-gunfight aim controller");
  if (!imuBegin()) {
    Serial.println("# ERROR imu not responding at 0x68");
  } else {
    Serial.println("# imu ok @0x68");
    calibrate();
  }
  Serial.printf("# gyro range +-%d dps, %.1f LSB/dps, deadzone %.3f dps\n",
                GYRO_FS_DPS, GYRO_LSB, GYRO_DEADZONE);
  Serial.println("# fields: AIM,ms,pitch,yaw,roll,trigger,shots");
}

// Peak rates say how much of the range play actually uses; clips say when the
// sensor ran out of range and the motion was lost.
static void reportPeaks(const Vec3 &rot) {
  gyro_peak.x = max(gyro_peak.x, fabsf(rot.x));
  gyro_peak.y = max(gyro_peak.y, fabsf(rot.y));
  gyro_peak.z = max(gyro_peak.z, fabsf(rot.z));

  uint32_t now = millis();
  if (now - peak_report_ms < 1000) return;
  peak_report_ms = now;
  Serial.printf("# PEAK gx=%.1f gy=%.1f gz=%.1f dps clips=%lu\n", gyro_peak.x,
                gyro_peak.y, gyro_peak.z, gyro_clips);
  gyro_peak = {0, 0, 0};
}

void loop() {
  // 'c' recalibrates bias, 'z' re-centres yaw.
  while (Serial.available()) {
    char c = Serial.read();
    if (c == 'c' || c == 'C') calibrate();
    if (c == 'z' || c == 'Z') {
      attitude.zeroYaw();
      Serial.println("# yaw zeroed");
    }
  }

  pollTrigger();

  uint32_t now = micros();
  if ((uint32_t)(now - last_us) < SAMPLE_US) return;
  float dt = (now - last_us) / 1000000.0f;
  last_us = now;

  Vec3 acc, rot;
  float temp_c;
  if (!readImu(acc, rot, temp_c)) {
    Serial.println("# imu read fail");
    delay(50);
    return;
  }

  reportPeaks(rot);

  // Fed the raw reading, not the corrected one: the tracker judges stillness
  // from how much the gyro varies, and a wrong bias must not hide that.
  bias_tracker.update(rot, acc, dt);
  if (bias_tracker.consumeSnap()) {
    // Yaw up to here was integrated under a bias now known to be wrong, so it
    // is not an aim offset worth keeping. Left alone it would bleed off at 2%
    // per second from wherever the bad bias had driven it.
    attitude.zeroYaw();
    const Vec3 b = bias_tracker.bias();
    Serial.printf("# BIAS recovered %.3f,%.3f,%.3f - yaw re-centred\n", b.x,
                  b.y, b.z);
  }
  attitude.update(acc, bias_tracker.correct(rot), dt);

  uint32_t now_ms = millis();
  if (now_ms - bias_report_ms >= 5000) {
    bias_report_ms = now_ms;
    const Vec3 b = bias_tracker.bias();
    Serial.printf("# BIAS %.3f,%.3f,%.3f still=%d trusted=%d wander=%.2f\n",
                  b.x, b.y, b.z, bias_tracker.still() ? 1 : 0,
                  bias_tracker.trusted() ? 1 : 0, bias_tracker.wander());
  }

  Serial.printf("AIM,%lu,%.2f,%.2f,%.2f,%d,%lu\n", millis(), attitude.pitch(),
                attitude.yaw(), attitude.roll(), trigger.pressed() ? 1 : 0,
                (unsigned long)trigger.shots());
}
