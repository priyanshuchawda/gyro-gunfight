#include <Arduino.h>
#include <Wire.h>
#include <math.h>
#include <stdarg.h>
#include <BLEDevice.h>
#include <BLEServer.h>
#include <BLEUtils.h>
#include <BLE2902.h>

#include "attitude.h"
#include "bias.h"
#include "trigger.h"

// ESP32 DevKit pinout used by this sketch.
static const int PIN_SDA = 21;
static const int PIN_SCL = 22;
static const int PIN_TRIGGER = 27;  // button to GND, INPUT_PULLUP
// Coin (pancake) vibrator via NPN/MOSFET — see README. Active HIGH.
static const int PIN_VIBE = 26;
static const uint32_t VIBE_FIRE_MS = 45;
static const uint32_t VIBE_HIT_MS = 140;

static const char *BLE_NAME = "GyroGun";

// Nordic UART Service — bleak / phone apps treat this as a serial pipe.
#define NUS_SERVICE_UUID           "6E400001-B5A3-F393-E0A9-E50E24DCCA9E"
#define NUS_CHARACTERISTIC_UUID_RX "6E400002-B5A3-F393-E0A9-E50E24DCCA9E"
#define NUS_CHARACTERISTIC_UUID_TX "6E400003-B5A3-F393-E0A9-E50E24DCCA9E"

static const uint8_t MPU_ADDR = 0x68;       // AD0 low; use 0x69 if AD0 is tied high
static const uint8_t MPU_WHO_AM_I_REG = 0x75;
static const uint8_t MPU6050_WHO_AM_I = 0x68;
// MPU-6050 temp: °C = TEMP_OUT/340 + 36.53 (not the 6500/9250 constants).
static const float MPU6050_TEMP_SENS = 340.0f;
static const float MPU6050_TEMP_OFFSET = 36.53f;
static const float ACC_LSB = 16384.0f;      // ±2 g

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

static const int16_t GYRO_CLIP_RAW = 32000;
static const float COMP_ALPHA = 0.98f;
static const float YAW_DECAY = 0.9998f;
static const float GYRO_DEADZONE = 8.0f / GYRO_LSB;
static const uint16_t SAMPLE_HZ = 100;
static const uint16_t SAMPLE_US = 1000000UL / SAMPLE_HZ;
static const uint32_t DEBOUNCE_MS = 25;

static const uint16_t BIAS_WINDOW = 60;
static const float BIAS_RATE_SPREAD = 2.0f;
static const float BIAS_ACC_SPREAD = 0.04f;
static const float BIAS_GAIN = 0.004f;
static const float BIAS_MAX_SLEW = 0.6f;

static AttitudeFilter attitude(COMP_ALPHA, YAW_DECAY, GYRO_DEADZONE);
static BiasTracker bias_tracker(BIAS_WINDOW, BIAS_RATE_SPREAD, BIAS_ACC_SPREAD,
                                BIAS_GAIN, BIAS_MAX_SLEW);
static TriggerDebouncer trigger(DEBOUNCE_MS);

static uint32_t bias_report_ms = 0;
static uint32_t last_us = 0;
static uint32_t gyro_clips = 0;
static Vec3 gyro_peak = {0, 0, 0};
static uint32_t peak_report_ms = 0;
static volatile bool request_calibrate = false;
static uint32_t vibe_until_ms = 0;
static uint32_t last_shot_count = 0;

static BLEServer *ble_server = nullptr;
static BLECharacteristic *ble_tx = nullptr;
static volatile bool ble_connected = false;
static char line_buf[160];

static void emitLine(const char *line) {
  Serial.println(line);
  if (!ble_connected || ble_tx == nullptr) return;
  ble_tx->setValue((uint8_t *)line, strlen(line));
  ble_tx->notify();
}

static void emitf(const char *fmt, ...) {
  va_list args;
  va_start(args, fmt);
  vsnprintf(line_buf, sizeof(line_buf), fmt, args);
  va_end(args);
  emitLine(line_buf);
}

static void buzz(uint32_t ms) {
  if (ms == 0) return;
  digitalWrite(PIN_VIBE, HIGH);
  uint32_t until = millis() + ms;
  // Keep the longest pending pulse if one is already running.
  if (until > vibe_until_ms) vibe_until_ms = until;
}

static void pollVibe() {
  if (vibe_until_ms != 0 && (int32_t)(millis() - vibe_until_ms) >= 0) {
    digitalWrite(PIN_VIBE, LOW);
    vibe_until_ms = 0;
  }
}

static void handleHostCommand(char c) {
  if (c == 'c' || c == 'C') request_calibrate = true;
  if (c == 'z' || c == 'Z') {
    attitude.zeroYaw();
    emitLine("# yaw zeroed");
  }
  // Phone-style coin vibrator pulses from the game.
  if (c == 'v') buzz(VIBE_FIRE_MS);
  if (c == 'h') buzz(VIBE_HIT_MS);
}

class ServerCallbacks : public BLEServerCallbacks {
  void onConnect(BLEServer *) override { ble_connected = true; }
  void onDisconnect(BLEServer *server) override {
    ble_connected = false;
    server->getAdvertising()->start();
  }
};

class RxCallbacks : public BLECharacteristicCallbacks {
  void onWrite(BLECharacteristic *characteristic) override {
    std::string value = characteristic->getValue();
    for (size_t i = 0; i < value.size(); i++) {
      handleHostCommand(value[i]);
    }
  }
};

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
  temp_c = be16(raw[6], raw[7]) / MPU6050_TEMP_SENS + MPU6050_TEMP_OFFSET;

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

static bool readWhoAmI(uint8_t &who) {
  return readBytes(MPU_WHO_AM_I_REG, &who, 1);
}

static bool imuBegin() {
  // MPU-6050 bring-up (InvenSense register map). Same FS/DLPF addresses as
  // the 6500 family, but WHO_AM_I and temperature scale differ.
  writeReg(0x6B, 0x80);  // device reset
  delay(100);
  writeReg(0x6B, 0x00);  // wake
  delay(50);
  writeReg(0x6B, 0x01);  // PLL with X gyro clock (stable on 6050)
  writeReg(0x1A, 0x03);  // DLPF ~44 Hz
  writeReg(0x19, 0x00);  // sample divider → 1 kHz
  writeReg(0x1B, GYRO_FS_SEL);
  writeReg(0x1C, 0x00);  // accel ±2 g
  delay(50);

  uint8_t who = 0;
  if (!readWhoAmI(who)) return false;
  if (who == MPU6050_WHO_AM_I) {
    emitf("# imu WHO_AM_I=0x%02X => MPU-6050 @0x%02X", who, MPU_ADDR);
  } else if (who == 0x70 || who == 0x71 || who == 0x73) {
    // Still usable for aim (same gyro/accel regs); warn so wiring is clear.
    emitf("# imu WHO_AM_I=0x%02X (not MPU-6050) @0x%02X — continuing", who,
          MPU_ADDR);
  } else {
    emitf("# imu WHO_AM_I=0x%02X unexpected @0x%02X — check wiring/AD0", who,
          MPU_ADDR);
  }
  return true;
}

static const float CAL_MAX_WANDER = 3.0f;
static const uint8_t CAL_ATTEMPTS = 4;

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
      lo.x = min(lo.x, rot.x);
      hi.x = max(hi.x, rot.x);
      lo.y = min(lo.y, rot.y);
      hi.y = max(hi.y, rot.y);
      lo.z = min(lo.z, rot.z);
      hi.z = max(hi.z, rot.z);
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
  emitLine("# CAL start - hold the gun still");

  Vec3 best = {0, 0, 0};
  float best_wander = 1e9f;
  bool clean = false;

  for (uint8_t attempt = 1; attempt <= CAL_ATTEMPTS && !clean; attempt++) {
    Vec3 measured;
    const float wander = measureBias(samples, measured);
    if (wander < 0) {
      emitLine("# CAL failed - no IMU data");
      return;
    }
    if (wander < best_wander) {
      best_wander = wander;
      best = measured;
    }
    clean = wander <= CAL_MAX_WANDER;
    if (!clean) {
      emitf("# CAL attempt %u saw %.1f dps of movement, retrying - "
            "put the gun down",
            attempt, wander);
    }
  }

  Vec3 acc, rot;
  float t;
  bias_tracker.seed(best, clean);
  if (readImu(acc, rot, t)) attitude.seed(acc);
  last_us = micros();

  if (clean) {
    emitf("# CAL done bias=%.3f,%.3f,%.3f wander=%.2f", best.x, best.y, best.z,
          best_wander);
  } else {
    emitf("# CAL UNTRUSTED after %u attempts, best wander %.1f dps - "
          "hold the gun still for a second and it will fix itself",
          CAL_ATTEMPTS, best_wander);
  }
}

static void pollTrigger() {
  trigger.update(digitalRead(PIN_TRIGGER) == LOW, millis());
}

static void setupBle() {
  BLEDevice::init(BLE_NAME);
  ble_server = BLEDevice::createServer();
  ble_server->setCallbacks(new ServerCallbacks());

  BLEService *service = ble_server->createService(NUS_SERVICE_UUID);
  ble_tx = service->createCharacteristic(
      NUS_CHARACTERISTIC_UUID_TX, BLECharacteristic::PROPERTY_NOTIFY);
  ble_tx->addDescriptor(new BLE2902());

  BLECharacteristic *ble_rx = service->createCharacteristic(
      NUS_CHARACTERISTIC_UUID_RX,
      BLECharacteristic::PROPERTY_WRITE |
          BLECharacteristic::PROPERTY_WRITE_NR);
  ble_rx->setCallbacks(new RxCallbacks());

  service->start();
  BLEAdvertising *advertising = BLEDevice::getAdvertising();
  advertising->addServiceUUID(NUS_SERVICE_UUID);
  advertising->setScanResponse(true);
  BLEDevice::startAdvertising();
}

void setup() {
  Serial.begin(115200);
  delay(400);
  pinMode(PIN_TRIGGER, INPUT_PULLUP);
  pinMode(PIN_VIBE, OUTPUT);
  digitalWrite(PIN_VIBE, LOW);

  Wire.begin(PIN_SDA, PIN_SCL);
  Wire.setClock(400000);

  Serial.println();
  Serial.println("# gyro-gunfight aim controller (ESP32 DevKit BLE)");
  setupBle();
  Serial.printf("# BLE advertising as %s (NUS)\n", BLE_NAME);

  if (!imuBegin()) {
    emitLine("# ERROR MPU-6050 not responding at 0x68 (check SDA=21 SCL=22)");
  } else {
    emitLine("# MPU-6050 ready");
    calibrate();
  }
  emitf("# gyro range +-%d dps, %.1f LSB/dps, deadzone %.3f dps", GYRO_FS_DPS,
        GYRO_LSB, GYRO_DEADZONE);
  emitLine("# fields: AIM,ms,pitch,yaw,roll,trigger,shots");
  emitLine("# transport: BLE UART (USB serial mirrored for debug)");
  emitLine("# haptics: coin vibe on GPIO26 — host 'v'=fire 'h'=hit");
  buzz(80);  // boot chirp so wiring is obvious
}

static void reportPeaks(const Vec3 &rot) {
  gyro_peak.x = max(gyro_peak.x, fabsf(rot.x));
  gyro_peak.y = max(gyro_peak.y, fabsf(rot.y));
  gyro_peak.z = max(gyro_peak.z, fabsf(rot.z));

  uint32_t now = millis();
  if (now - peak_report_ms < 1000) return;
  peak_report_ms = now;
  emitf("# PEAK gx=%.1f gy=%.1f gz=%.1f dps clips=%lu", gyro_peak.x,
        gyro_peak.y, gyro_peak.z, (unsigned long)gyro_clips);
  gyro_peak = {0, 0, 0};
}

void loop() {
  while (Serial.available()) {
    handleHostCommand((char)Serial.read());
  }
  if (request_calibrate) {
    request_calibrate = false;
    calibrate();
  }

  pollTrigger();
  pollVibe();
  // Local fire haptic even if the PC never answers (miss / no BLE client).
  if (trigger.shots() != last_shot_count) {
    last_shot_count = trigger.shots();
    buzz(VIBE_FIRE_MS);
  }

  uint32_t now = micros();
  if ((uint32_t)(now - last_us) < SAMPLE_US) return;
  float dt = (now - last_us) / 1000000.0f;
  last_us = now;

  Vec3 acc, rot;
  float temp_c;
  if (!readImu(acc, rot, temp_c)) {
    emitLine("# imu read fail");
    delay(50);
    return;
  }

  reportPeaks(rot);

  bias_tracker.update(rot, acc, dt);
  if (bias_tracker.consumeSnap()) {
    attitude.zeroYaw();
    const Vec3 b = bias_tracker.bias();
    emitf("# BIAS recovered %.3f,%.3f,%.3f - yaw re-centred", b.x, b.y, b.z);
  }
  attitude.update(acc, bias_tracker.correct(rot), dt);

  uint32_t now_ms = millis();
  if (now_ms - bias_report_ms >= 5000) {
    bias_report_ms = now_ms;
    const Vec3 b = bias_tracker.bias();
    emitf("# BIAS %.3f,%.3f,%.3f still=%d trusted=%d wander=%.2f", b.x, b.y,
          b.z, bias_tracker.still() ? 1 : 0, bias_tracker.trusted() ? 1 : 0,
          bias_tracker.wander());
  }

  // ~100 Hz on USB; ~100 Hz BLE notifies when a client is connected.
  static uint32_t last_ble_ms = 0;
  const bool send_ble = ble_connected && (now_ms - last_ble_ms >= 10);
  if (send_ble) last_ble_ms = now_ms;

  snprintf(line_buf, sizeof(line_buf), "AIM,%lu,%.2f,%.2f,%.2f,%d,%lu",
           (unsigned long)millis(), attitude.pitch(), attitude.yaw(),
           attitude.roll(), trigger.pressed() ? 1 : 0,
           (unsigned long)trigger.shots());
  Serial.println(line_buf);
  // Append newline so the host can split the same way as USB Serial.println.
  size_t n = strlen(line_buf);
  if (n + 1 < sizeof(line_buf)) {
    line_buf[n] = '\n';
    line_buf[n + 1] = '\0';
    n += 1;
  }
  if (send_ble && ble_tx != nullptr) {
    ble_tx->setValue((uint8_t *)line_buf, n);
    ble_tx->notify();
  }
}
