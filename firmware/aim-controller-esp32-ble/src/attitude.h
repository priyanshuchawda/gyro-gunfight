#pragma once
#include <math.h>
#include <stdint.h>

struct Vec3 {
  float x, y, z;
};

// Complementary filter turning IMU samples into an aiming attitude.
//
// Free of Arduino calls for the same reason as the trigger: the behaviour that
// matters is how it responds over thousands of samples to gyro bias, hand
// shake and sustained rotation, and none of that can be judged by waving the
// board around and watching a crosshair.
class AttitudeFilter {
 public:
  AttitudeFilter(float comp_alpha, float yaw_decay, float deadzone_dps)
      : alpha_(comp_alpha), yaw_decay_(yaw_decay), deadzone_(deadzone_dps) {}

  // Gravity alone fixes pitch and roll, so a fresh start can jump straight to
  // the right attitude instead of easing in from zero.
  void seed(const Vec3 &acc) {
    roll_ = accRoll(acc);
    pitch_ = accPitch(acc);
    yaw_ = 0;
  }

  void zeroYaw() { yaw_ = 0; }

  // rot is bias-corrected body rate in dps, dt in seconds.
  void update(const Vec3 &acc, const Vec3 &rot, float dt) {
    const float gx = deadzone(rot.x);
    const float gy = deadzone(rot.y);
    const float gz = deadzone(rot.z);

    // The gyro term carries the fast motion and the accelerometer term pins
    // the result to gravity, which cannot drift. Blending both means a steady
    // gyro bias cannot walk pitch or roll away.
    roll_ = alpha_ * (roll_ + gx * dt) + (1.0f - alpha_) * accRoll(acc);
    pitch_ = alpha_ * (pitch_ + gy * dt) + (1.0f - alpha_) * accPitch(acc);

    // Yaw has no such anchor without a magnetometer, so it is bled back to
    // centre rather than left to walk the crosshair off screen.
    yaw_ = (yaw_ + gz * dt) * yaw_decay_;
  }

  float pitch() const { return pitch_; }
  float roll() const { return roll_; }
  float yaw() const { return yaw_; }

  float deadzone(float v) const { return fabsf(v) < deadzone_ ? 0.0f : v; }

  // Attitude implied by gravity alone, valid only while the board is not
  // being accelerated by anything but gravity.
  static float accRoll(const Vec3 &a) { return atan2f(a.y, a.z) * 57.2957795f; }
  static float accPitch(const Vec3 &a) {
    return atan2f(-a.x, sqrtf(a.y * a.y + a.z * a.z)) * 57.2957795f;
  }

 private:
  float alpha_;
  float yaw_decay_;
  float deadzone_;
  float pitch_ = 0, roll_ = 0, yaw_ = 0;
};
