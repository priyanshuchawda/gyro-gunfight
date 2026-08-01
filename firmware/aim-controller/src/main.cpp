#include <Arduino.h>
#include <Wire.h>
#include <math.h>

// NodeMCU I2C
static const int PIN_SDA = 4;  // D2
static const int PIN_SCL = 5;  // D1
// Trigger button to GND (optional, may be unwired)
static const int PIN_TRIGGER = 14;  // D5

static const uint8_t MPU_ADDR = 0x68;

static const float DEG = 57.2957795f;
static const float GYRO_LSB = 131.0f;    // +-250 dps
static const float ACC_LSB = 16384.0f;   // +-2 g

// Accel is trusted slowly so hand shake does not fight the gyro.
static const float COMP_ALPHA = 0.98f;
// Yaw has no absolute reference (no magnetometer), so bleed it back to
// centre instead of letting residual bias walk the crosshair off screen.
static const float YAW_DECAY = 0.995f;
static const float GYRO_DEADZONE = 0.06f;  // dps

static const uint16_t SAMPLE_HZ = 100;
static const uint16_t SAMPLE_US = 1000000UL / SAMPLE_HZ;

struct Vec3 {
  float x, y, z;
};

static Vec3 gyro_bias = {0, 0, 0};
static float pitch = 0, roll = 0, yaw = 0;
static uint32_t last_us = 0;
static bool calibrated = false;

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
  rot.x = be16(raw[8], raw[9]) / GYRO_LSB;
  rot.y = be16(raw[10], raw[11]) / GYRO_LSB;
  rot.z = be16(raw[12], raw[13]) / GYRO_LSB;
  return true;
}

static bool imuBegin() {
  writeReg(0x6B, 0x80);  // reset
  delay(100);
  writeReg(0x6B, 0x00);  // wake
  delay(50);
  writeReg(0x6B, 0x01);  // gyro X clock
  writeReg(0x1A, 0x03);  // DLPF 44 Hz
  writeReg(0x19, 0x00);  // 1 kHz sample
  writeReg(0x1B, 0x00);  // gyro +-250 dps
  writeReg(0x1C, 0x00);  // accel +-2 g
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

  if (readImu(acc, rot, t)) {
    roll = atan2f(acc.y, acc.z) * DEG;
    pitch = atan2f(-acc.x, sqrtf(acc.y * acc.y + acc.z * acc.z)) * DEG;
  }
  yaw = 0;
  calibrated = true;
  last_us = micros();
  Serial.printf("# CAL done bias=%.3f,%.3f,%.3f samples=%u\n",
                gyro_bias.x, gyro_bias.y, gyro_bias.z, got);
}

static float deadzone(float v) {
  return fabsf(v) < GYRO_DEADZONE ? 0.0f : v;
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
  Serial.println("# fields: AIM,ms,pitch,yaw,roll,trigger");
}

void loop() {
  // 'c' recalibrates bias, 'z' re-centres yaw.
  while (Serial.available()) {
    char c = Serial.read();
    if (c == 'c' || c == 'C') calibrate();
    if (c == 'z' || c == 'Z') {
      yaw = 0;
      Serial.println("# yaw zeroed");
    }
  }

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

  float gx = deadzone(rot.x - gyro_bias.x);
  float gy = deadzone(rot.y - gyro_bias.y);
  float gz = deadzone(rot.z - gyro_bias.z);

  float acc_roll = atan2f(acc.y, acc.z) * DEG;
  float acc_pitch = atan2f(-acc.x, sqrtf(acc.y * acc.y + acc.z * acc.z)) * DEG;

  roll = COMP_ALPHA * (roll + gx * dt) + (1.0f - COMP_ALPHA) * acc_roll;
  pitch = COMP_ALPHA * (pitch + gy * dt) + (1.0f - COMP_ALPHA) * acc_pitch;
  yaw = (yaw + gz * dt) * YAW_DECAY;

  int trigger = (digitalRead(PIN_TRIGGER) == LOW) ? 1 : 0;

  Serial.printf("AIM,%lu,%.2f,%.2f,%.2f,%d\n", millis(), pitch, yaw, roll,
                trigger);
}
