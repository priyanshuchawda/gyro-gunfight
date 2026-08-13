#pragma once
#include <math.h>
#include <stdint.h>

#include "attitude.h"  // Vec3

// Keeps the gyro bias estimate correct while the gun is in use.
//
// Boot calibration alone is not enough. It averages a second or so of gyro and
// assumes the gun is motionless, so being picked up during those samples bakes
// the movement in as "bias". Yaw has no magnetometer to argue with that, and
// the filter's decay settles yaw at roughly fifty times the residual bias, so
// an error of half a degree per second parks the crosshair off the side of the
// screen. Gyro bias also walks with temperature, which no boot-time
// measurement can predict.
//
// The recovery is a zero-rate update: whenever the gun is demonstrably
// stationary, whatever the gyro reads at that moment *is* the bias, so the
// estimate is eased toward it.
//
// One case stays genuinely unobservable: a perfectly constant yaw pan. Yawing
// a level gun leaves gravity exactly where it was, so nothing distinguishes it
// from bias. Human hands do not pan that smoothly, which the gyro spread check
// catches, and the gain is deliberately slow so a few seconds of an unusually
// smooth pan barely moves the estimate.
//
// Stillness is judged by how much the raw gyro varies, never by how large the
// bias-corrected rate is. That distinction is the whole point. A stationary
// gyro reads a constant, and that constant is its bias; if the current
// estimate is badly wrong the corrected rate is large *precisely when* the
// correction is most needed, so any threshold on it would lock the tracker out
// of fixing itself.
class BiasTracker {
 public:
  static const uint16_t kMaxWindow = 64;

  // rate_spread_dps: how much the raw gyro may wander and still count as still.
  // acc_spread_g: same for the accelerometer, which catches translation.
  // gain: fraction of the error absorbed per sample while still.
  // max_slew_dps_s: hard ceiling on how fast the estimate may move.
  BiasTracker(uint16_t window, float rate_spread_dps, float acc_spread_g,
              float gain, float max_slew_dps_s)
      : window_(window < kMaxWindow ? window : kMaxWindow),
        rate_spread_(rate_spread_dps),
        acc_spread_(acc_spread_g),
        gain_(gain),
        max_slew_(max_slew_dps_s) {}

  // `trusted` says whether the seed is believable. An untrusted seed -- one
  // measured while the gun was clearly moving -- is thrown away and replaced
  // outright by the first still window, rather than eased toward over the
  // best part of a minute. A calibration taken mid-swing can be tens of dps
  // out, and easing away from that at the slew limit is not a recovery.
  void seed(const Vec3 &bias, bool trusted = true) {
    bias_ = bias;
    trusted_ = trusted;
    snapped_ = false;
    filled_ = 0;
    head_ = 0;
    still_ = false;
  }

  // Feed the raw, uncorrected gyro reading and the accelerometer, in dps and g.
  // Returns true when this sample moved the estimate.
  bool update(const Vec3 &rot, const Vec3 &acc, float dt) {
    gx_[head_] = rot.x;
    gy_[head_] = rot.y;
    gz_[head_] = rot.z;
    ax_[head_] = acc.x;
    ay_[head_] = acc.y;
    az_[head_] = acc.z;
    head_ = (uint16_t)((head_ + 1) % window_);
    if (filled_ < window_) {
      filled_++;
      still_ = false;
      return false;
    }

    // Per axis, not on the magnitude. Rotating the gun swings gravity from one
    // accelerometer axis to another while its length stays exactly 1 g, so a
    // magnitude check sees a steady tilting pan as perfectly stationary and
    // quietly eats the player's own movement as bias.
    const float mx = mean(ax_), my = mean(ay_), mz = mean(az_);
    wander_ = spread(gx_);
    if (spread(gy_) > wander_) wander_ = spread(gy_);
    if (spread(gz_) > wander_) wander_ = spread(gz_);
    still_ = wander_ < rate_spread_ && spread(ax_) < acc_spread_ &&
             spread(ay_) < acc_spread_ && spread(az_) < acc_spread_ &&
             fabsf(sqrtf(mx * mx + my * my + mz * mz) - 1.0f) < 0.15f;
    if (!still_) return false;

    // First good look at a stationary gun after a calibration that cannot be
    // believed: take the reading as the truth and start trusting it.
    if (!trusted_) {
      bias_ = {mean(gx_), mean(gy_), mean(gz_)};
      trusted_ = true;
      snapped_ = true;
      return true;
    }

    // Recovering from a bad calibration and absorbing the player's own pan are
    // the same motion in reverse, so no gain can be quick at one and slow at
    // the other. The slew limit puts a hard ceiling on both: it is well above
    // any real thermal drift, and it bounds what an undetectably smooth pan
    // can cost before the gun is held still again and the estimate recovers.
    const float step = max_slew_ * dt;
    bias_.x += clamp((mean(gx_) - bias_.x) * gain_, step);
    bias_.y += clamp((mean(gy_) - bias_.y) * gain_, step);
    bias_.z += clamp((mean(gz_) - bias_.z) * gain_, step);
    return true;
  }

  Vec3 bias() const { return bias_; }
  bool still() const { return still_; }
  bool trusted() const { return trusted_; }

  // Largest gyro spread across the window, in dps. Reported so the stillness
  // threshold can be judged against what a hand actually achieves rather than
  // against a guess.
  float wander() const { return wander_; }

  // True once after the estimate has been replaced wholesale. Whatever yaw was
  // integrated under the discarded bias is meaningless, so the caller is
  // expected to throw it away too.
  bool consumeSnap() {
    const bool s = snapped_;
    snapped_ = false;
    return s;
  }

  Vec3 correct(const Vec3 &rot) const {
    return {rot.x - bias_.x, rot.y - bias_.y, rot.z - bias_.z};
  }

 private:
  static float clamp(float v, float limit) {
    if (v > limit) return limit;
    if (v < -limit) return -limit;
    return v;
  }

  float mean(const float *buf) const {
    float sum = 0;
    for (uint16_t i = 0; i < window_; i++) sum += buf[i];
    return sum / window_;
  }

  float spread(const float *buf) const {
    float lo = buf[0], hi = buf[0];
    for (uint16_t i = 1; i < window_; i++) {
      if (buf[i] < lo) lo = buf[i];
      if (buf[i] > hi) hi = buf[i];
    }
    return hi - lo;
  }

  uint16_t window_;
  float rate_spread_;
  float acc_spread_;
  float gain_;
  float max_slew_;

  float gx_[kMaxWindow] = {0};
  float gy_[kMaxWindow] = {0};
  float gz_[kMaxWindow] = {0};
  float ax_[kMaxWindow] = {0};
  float ay_[kMaxWindow] = {0};
  float az_[kMaxWindow] = {0};
  uint16_t head_ = 0;
  uint16_t filled_ = 0;
  bool still_ = false;
  bool trusted_ = true;
  bool snapped_ = false;
  float wander_ = 0;
  Vec3 bias_ = {0, 0, 0};
};
