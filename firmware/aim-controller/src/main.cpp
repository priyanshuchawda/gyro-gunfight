#include <Arduino.h>
#include <Wire.h>
#include <math.h>

#include "attitude.h"
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

static Vec3 gyro_bias = {0, 0, 0};

// Same implementation the host tests drive; see test/test_attitude.cpp.
static AttitudeFilter attitude(COMP_ALPHA, YAW_DECAY, GYRO_DEADZONE);
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

static void calibrate(uint16_t samples = 400) {
  Serial.println("# CAL start - hold the gun still");
  Vec3 sum = {0, 0, 0};
  Vec3 acc, rot;
  float t;
  uint16_t got = 0;
  for (uint16_t i = 0; i < samples; i++) {
    if (readImu(acc, rot, t)) {
      sum.x += rot.x;
      sum.y += rot.y;
      sum.z += rot.z;
      got++;
    }
    delay(3);
  }
  if (got == 0) {
    Serial.println("# CAL failed - no IMU data");
    return;
  }
  gyro_bias.x = sum.x / got;
  gyro_bias.y = sum.y / got;
  gyro_bias.z = sum.z / got;

  if (readImu(acc, rot, t)) attitude.seed(acc);
  calibrated = true;
  last_us = micros();
  Serial.printf("# CAL done bias=%.3f,%.3f,%.3f samples=%u\n",
                gyro_bias.x, gyro_bias.y, gyro_bias.z, got);
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

  const Vec3 rate = {rot.x - gyro_bias.x, rot.y - gyro_bias.y,
                     rot.z - gyro_bias.z};
  attitude.update(acc, rate, dt);

  Serial.printf("AIM,%lu,%.2f,%.2f,%.2f,%d,%lu\n", millis(), attitude.pitch(),
                attitude.yaw(), attitude.roll(), trigger.pressed() ? 1 : 0,
                (unsigned long)trigger.shots());
}
