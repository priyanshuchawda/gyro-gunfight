// Host tests for the complementary filter. Build and run:
//
//   g++ -std=c++11 -Wall -Wextra -o /tmp/test_attitude
//       firmware/aim-controller/test/test_attitude.cpp && /tmp/test_attitude
//
// These drive the same header the firmware uses. The behaviour worth checking
// only shows up over thousands of samples: whether a steady gyro bias walks
// the aim away, whether hand shake reaches the crosshair, whether yaw returns
// to centre. Waving the board around cannot answer any of that.

#include "../src/attitude.h"

#include <cstdio>
#include <cstdlib>
#include <string>

static int failures = 0;

static void near(const std::string &name, float got, float want, float tol) {
  if (fabsf(got - want) <= tol) {
    printf("  ok    %-48s %8.3f\n", name.c_str(), got);
  } else {
    printf("  FAIL  %-48s got %.3f, want %.3f +-%.3f\n", name.c_str(), got,
           want, tol);
    failures++;
  }
}

static void below(const std::string &name, float got, float limit) {
  if (got < limit) {
    printf("  ok    %-48s %8.3f < %.3f\n", name.c_str(), got, limit);
  } else {
    printf("  FAIL  %-48s got %.3f, wanted < %.3f\n", name.c_str(), got, limit);
    failures++;
  }
}

// Firmware settings, so the tests describe the shipped configuration.
static const float ALPHA = 0.98f;
static const float YAW_DECAY = 0.995f;
static const float DEADZONE = 8.0f / 32.8f;  // +-1000 dps range
static const float DT = 0.01f;               // 100 Hz
static const Vec3 STILL = {0, 0, 0};

// Gravity as the accelerometer would report it at a given tilt, in g.
static Vec3 gravityAt(float pitch_deg, float roll_deg) {
  const float p = pitch_deg / 57.2957795f;
  const float r = roll_deg / 57.2957795f;
  return {-sinf(p), sinf(r) * cosf(p), cosf(r) * cosf(p)};
}

static void settle(AttitudeFilter &f, const Vec3 &acc, int samples) {
  for (int i = 0; i < samples; i++) f.update(acc, STILL, DT);
}

int main() {
  printf("complementary filter, alpha %.2f, yaw decay %.3f, %.0f Hz\n\n", ALPHA,
         YAW_DECAY, 1.0f / DT);

  {
    AttitudeFilter f(ALPHA, YAW_DECAY, DEADZONE);
    f.seed(gravityAt(0, 0));
    near("level board reads level in pitch", f.pitch(), 0.0f, 0.01f);
    near("level board reads level in roll", f.roll(), 0.0f, 0.01f);
  }

  {
    // Held at a tilt with no rotation, the filter has to converge on what
    // gravity says rather than sitting wherever it started.
    AttitudeFilter f(ALPHA, YAW_DECAY, DEADZONE);
    settle(f, gravityAt(30, 0), 2000);
    near("converges to a 30 deg pitch from cold", f.pitch(), 30.0f, 0.5f);

    AttitudeFilter g(ALPHA, YAW_DECAY, DEADZONE);
    settle(g, gravityAt(0, -20), 2000);
    near("converges to a -20 deg roll from cold", g.roll(), -20.0f, 0.5f);
  }

  {
    // Seeding exists so a fresh calibration does not spend a second easing in.
    AttitudeFilter f(ALPHA, YAW_DECAY, DEADZONE);
    f.seed(gravityAt(40, 0));
    near("seeding jumps straight to gravity", f.pitch(), 40.0f, 0.01f);
  }

  {
    // The whole point of blending in the accelerometer. An uncorrected bias
    // of 2 dps would integrate to 120 degrees over a minute; gravity has to
    // hold pitch in place instead.
    AttitudeFilter f(ALPHA, YAW_DECAY, DEADZONE);
    const Vec3 level = gravityAt(0, 0);
    const Vec3 biased = {0, 2.0f, 0};
    for (int i = 0; i < 6000; i++) f.update(level, biased, DT);
    below("2 dps bias cannot walk pitch over a minute", fabsf(f.pitch()), 2.0f);
  }

  {
    // Yaw has no gravity anchor, so the decay is all that stops it leaving.
    // Without it this same bias would reach 120 degrees.
    AttitudeFilter f(ALPHA, YAW_DECAY, DEADZONE);
    const Vec3 level = gravityAt(0, 0);
    const Vec3 biased = {0, 0, 2.0f};
    for (int i = 0; i < 6000; i++) f.update(level, biased, DT);
    below("yaw decay bounds a 2 dps bias", fabsf(f.yaw()), 5.0f);
  }

  {
    // A deliberate turn has to move the crosshair, but not by the textbook
    // 45 degrees: the decay compounds over the 50 samples and eats about an
    // eighth of the swing. Asserting the honest number keeps that cost visible
    // instead of hiding it inside a loose tolerance.
    //
    //   0.9 * sum(0.995^k, k=1..50) = 39.7
    AttitudeFilter f(ALPHA, YAW_DECAY, DEADZONE);
    const Vec3 level = gravityAt(0, 0);
    const Vec3 turning = {0, 0, 90.0f};  // 90 dps for half a second
    for (int i = 0; i < 50; i++) f.update(level, turning, DT);
    near("90 dps for 0.5 s yaws 39.7, not the ideal 45", f.yaw(), 39.7f, 0.5f);
  }

  {
    // The consequence of that decay at full stretch: yaw cannot exceed
    // rate * dt * d / (1 - d), which is 1.99 degrees per dps of turn rate, no
    // matter how far you keep turning. Sustained yaw tracks how fast you are
    // turning rather than how far you have turned. Without a magnetometer
    // there is no way around this, so it is pinned here rather than
    // discovered mid-game.
    AttitudeFilter fast(ALPHA, YAW_DECAY, DEADZONE);
    AttitudeFilter slow(ALPHA, YAW_DECAY, DEADZONE);
    const Vec3 level = gravityAt(0, 0);
    for (int i = 0; i < 4000; i++) {
      fast.update(level, {0, 0, 90.0f}, DT);
      slow.update(level, {0, 0, 30.0f}, DT);
    }
    near("a held 90 dps turn saturates near 179 deg", fast.yaw(), 179.1f, 1.0f);
    near("a held 30 dps turn saturates near 59.7 deg", slow.yaw(), 59.7f, 1.0f);
  }

  {
    // Released mid-turn, yaw has to come home rather than stick.
    AttitudeFilter f(ALPHA, YAW_DECAY, DEADZONE);
    const Vec3 level = gravityAt(0, 0);
    for (int i = 0; i < 50; i++) f.update(level, {0, 0, 90.0f}, DT);
    const float peak = f.yaw();
    for (int i = 0; i < 1000; i++) f.update(level, STILL, DT);
    below("yaw returns to centre once the turn stops", fabsf(f.yaw()),
          fabsf(peak) * 0.05f);
  }

  {
    // Hand shake is the accelerometer lying about which way is down. Alpha is
    // 0.98 precisely so this does not reach the crosshair.
    // Comparing against the raw accelerometer rather than a threshold picked
    // out of the air: what matters is how much of the shake the filter removes,
    // which stays meaningful whatever amplitude the test uses.
    AttitudeFilter f(ALPHA, YAW_DECAY, DEADZONE);
    f.seed(gravityAt(0, 0));
    float worst_raw = 0, worst_filtered = 0;
    srand(7);
    for (int i = 0; i < 2000; i++) {
      Vec3 shaky = gravityAt(0, 0);
      shaky.x += ((rand() % 2001) - 1000) / 1000.0f * 0.3f;  // +-0.3 g
      shaky.y += ((rand() % 2001) - 1000) / 1000.0f * 0.3f;
      const float raw = fabsf(AttitudeFilter::accPitch(shaky));
      if (raw > worst_raw) worst_raw = raw;
      f.update(shaky, STILL, DT);
      if (fabsf(f.pitch()) > worst_filtered) worst_filtered = fabsf(f.pitch());
    }
    printf("        (raw accel swings %.1f deg under the same shake)\n",
           worst_raw);
    below("0.3 g of shake is attenuated at least 4x", worst_filtered,
          worst_raw / 4.0f);
  }

  {
    // Rates under the deadzone are sensor noise, not aiming, and must not
    // accumulate. This is a tenth of a count of drift per sample.
    AttitudeFilter f(ALPHA, YAW_DECAY, DEADZONE);
    const Vec3 level = gravityAt(0, 0);
    const Vec3 noise = {0, 0, DEADZONE * 0.9f};
    for (int i = 0; i < 6000; i++) f.update(level, noise, DT);
    near("sub-deadzone noise is ignored entirely", f.yaw(), 0.0f, 0.001f);

    // Just above it, the same rate must get through, or the deadzone would be
    // swallowing real aim.
    AttitudeFilter g(ALPHA, YAW_DECAY, DEADZONE);
    const Vec3 real = {0, 0, DEADZONE * 1.1f};
    for (int i = 0; i < 500; i++) g.update(level, real, DT);
    if (fabsf(g.yaw()) > 0.01f) {
      printf("  ok    %-48s %8.3f\n", "just above the deadzone still aims",
             g.yaw());
    } else {
      printf("  FAIL  %-48s got %.5f\n", "just above the deadzone still aims",
             g.yaw());
      failures++;
    }
  }

  {
    // Upside down is where a naive atan2 on one axis flips sign and the aim
    // snaps across the screen.
    AttitudeFilter f(ALPHA, YAW_DECAY, DEADZONE);
    settle(f, gravityAt(0, 170), 4000);
    near("holds together at 170 deg of roll", f.roll(), 170.0f, 1.0f);
  }

  {
    // zeroYaw backs the 'z' command; it must not disturb the other axes.
    AttitudeFilter f(ALPHA, YAW_DECAY, DEADZONE);
    settle(f, gravityAt(25, 0), 2000);
    for (int i = 0; i < 50; i++) f.update(gravityAt(25, 0), {0, 0, 90.0f}, DT);
    f.zeroYaw();
    near("zeroing yaw clears yaw", f.yaw(), 0.0f, 0.001f);
    near("zeroing yaw leaves pitch alone", f.pitch(), 25.0f, 0.5f);
  }

  printf("\n%s\n", failures ? "FAILURES" : "all attitude checks passed");
  return failures ? 1 : 0;
}
