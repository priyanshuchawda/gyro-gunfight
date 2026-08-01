#include <Arduino.h>
#include <Wire.h>
#include <math.h>

static const int SDA_PIN = 4;  // D2
static const int SCL_PIN = 5;  // D1
static const uint8_t MPU = 0x68;
static const uint8_t MAG = 0x0C; // AK8963 inside MPU9250

uint8_t writeReg(uint8_t addr, uint8_t reg, uint8_t val) {
  Wire.beginTransmission(addr);
  Wire.write(reg);
  Wire.write(val);
  return Wire.endTransmission();
}

uint8_t readBytes(uint8_t addr, uint8_t reg, uint8_t *buf, uint8_t n) {
  Wire.beginTransmission(addr);
  Wire.write(reg);
  if (Wire.endTransmission(false) != 0) return 1;
  if (Wire.requestFrom((int)addr, (int)n) != n) return 2;
  for (uint8_t i = 0; i < n; i++) buf[i] = Wire.read();
  return 0;
}

uint8_t read8(uint8_t addr, uint8_t reg, uint8_t *out) {
  return readBytes(addr, reg, out, 1);
}

int16_t be16(uint8_t hi, uint8_t lo) {
  return (int16_t)((hi << 8) | lo);
}

bool mag_ok = false;
float mag_adj[3] = {1, 1, 1};
const char *chip_name = "unknown";

void setupMPU() {
  writeReg(MPU, 0x6B, 0x00); // wake PWR_MGMT_1
  delay(100);
  writeReg(MPU, 0x6B, 0x01); // clock auto
  writeReg(MPU, 0x1A, 0x03); // DLPF
  writeReg(MPU, 0x1B, 0x00); // gyro ±250 dps
  writeReg(MPU, 0x1C, 0x00); // accel ±2g

  uint8_t who = 0;
  read8(MPU, 0x75, &who);
  if (who == 0x71) chip_name = "MPU9250";
  else if (who == 0x70) chip_name = "MPU6500";
  else if (who == 0x68) chip_name = "MPU6050";
  else if (who == 0x73) chip_name = "MPU9255";
  else chip_name = "MPU-family";

  Serial.printf("WHO_AM_I=0x%02X => %s @0x%02X\n", who, chip_name, MPU);

  // Enable I2C bypass so we can talk to AK8963 (9250/9255)
  writeReg(MPU, 0x37, 0x02); // INT_PIN_CFG bypass
  writeReg(MPU, 0x6A, 0x00); // USER_CTRL disable master
  delay(10);

  uint8_t mag_id = 0;
  if (read8(MAG, 0x00, &mag_id) == 0 && mag_id == 0x48) {
    mag_ok = true;
    writeReg(MAG, 0x0A, 0x00); // power down
    delay(10);
    writeReg(MAG, 0x0A, 0x0F); // fuse ROM
    delay(10);
    uint8_t asa[3];
    if (readBytes(MAG, 0x10, asa, 3) == 0) {
      for (int i = 0; i < 3; i++)
        mag_adj[i] = ((float)asa[i] - 128.0f) / 256.0f + 1.0f;
    }
    writeReg(MAG, 0x0A, 0x00);
    delay(10);
    writeReg(MAG, 0x0A, 0x16); // 16-bit continuous mode 2 (100Hz)
    Serial.printf("AK8963 mag OK id=0x%02X adj=%.3f,%.3f,%.3f\n",
                  mag_id, mag_adj[0], mag_adj[1], mag_adj[2]);
  } else {
    Serial.printf("No AK8963 mag (id read failed or 0x%02X) — accel/gyro only\n", mag_id);
  }
}

void i2cScan() {
  Serial.println("I2C scan:");
  for (uint8_t a = 1; a < 127; a++) {
    Wire.beginTransmission(a);
    if (Wire.endTransmission() == 0) Serial.printf("  0x%02X\n", a);
  }
}

void setup() {
  Serial.begin(115200);
  delay(600);
  Serial.println();
  Serial.println("=== MPU full reader ===");
  Wire.begin(SDA_PIN, SCL_PIN);
  Wire.setClock(100000);
  i2cScan();
  setupMPU();
  Serial.println("ax ay az | gx gy gz | mx my mz | temp");
}

void loop() {
  uint8_t raw[14];
  if (readBytes(MPU, 0x3B, raw, 14) != 0) {
    Serial.println("MPU read fail");
    delay(500);
    return;
  }

  float ax = be16(raw[0], raw[1]) / 16384.0f;
  float ay = be16(raw[2], raw[3]) / 16384.0f;
  float az = be16(raw[4], raw[5]) / 16384.0f;
  float temp = be16(raw[6], raw[7]) / 333.87f + 21.0f;
  float gx = be16(raw[8], raw[9]) / 131.0f;
  float gy = be16(raw[10], raw[11]) / 131.0f;
  float gz = be16(raw[12], raw[13]) / 131.0f;

  float mx = 0, my = 0, mz = 0;
  if (mag_ok) {
    uint8_t st1 = 0;
    if (read8(MAG, 0x02, &st1) == 0 && (st1 & 0x01)) {
      uint8_t m[7];
      if (readBytes(MAG, 0x03, m, 7) == 0 && !(m[6] & 0x08)) {
        // AK8963 little-endian
        int16_t rx = (int16_t)(m[1] << 8 | m[0]);
        int16_t ry = (int16_t)(m[3] << 8 | m[2]);
        int16_t rz = (int16_t)(m[5] << 8 | m[4]);
        mx = rx * 0.15f * mag_adj[0];
        my = ry * 0.15f * mag_adj[1];
        mz = rz * 0.15f * mag_adj[2];
      }
    }
  }

  float roll = atan2f(ay, az) * 57.2957795f;
  float pitch = atan2f(-ax, sqrtf(ay * ay + az * az)) * 57.2957795f;

  Serial.printf(
    "A:%6.2f %6.2f %6.2f g | G:%7.1f %7.1f %7.1f dps | M:%6.1f %6.1f %6.1f uT | T:%5.1fC | R/P:%6.1f/%6.1f\n",
    ax, ay, az, gx, gy, gz, mx, my, mz, temp, roll, pitch);

  delay(300);
}
