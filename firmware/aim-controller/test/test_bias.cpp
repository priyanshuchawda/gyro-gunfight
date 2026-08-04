// Host tests for the runtime gyro bias tracker. Build and run:
//
//   g++ -std=c++11 -Wall -Wextra -o /tmp/test_bias
//       firmware/aim-controller/test/test_bias.cpp && /tmp/test_bias
//
// The case that matters is the one that cannot be staged by hand: boot
// calibration running while the gun is being picked up, so the bias is wrong
// from the first sample and yaw walks off the screen. Reproducing that on the
// bench means catching the board mid-movement at power-on, and confirming a
// fix means watching a crosshair for a minute. Here it is a few lines.

#include "../src/attitude.h"
#include "../src/bias.h"

#include <cstdio>
#include <cstdlib>
#include <string>

static int failures = 0;

static void near(const std::string &name, float got, float want, float tol) {
  if (fabsf(got - want) <= tol) {
    printf("  ok    %-50s %8.3f\n", name.c_str(), got);
  } else {
    printf("  FAIL  %-50s got %.3f, want %.3f +-%.3f\n", name.c_str(), got,
           want, tol);
    failures++;
  }
}

static void below(const std::string &name, float got, float limit) {
  if (got < limit) {
    printf("  ok    %-50s %8.3f < %.3f\n", name.c_str(), got, limit);
  } else {
    printf("  FAIL  %-50s got %.3f, wanted < %.3f\n", name.c_str(), got, limit);
    failures++;
  }
}

static void is_true(const std::string &name, bool got) {
  if (got) {
    printf("  ok    %-50s\n", name.c_str());
  } else {
    printf("  FAIL  %-50s was false\n", name.c_str());
    failures++;
  }
}

// Firmware settings, so the tests describe the shipped configuration.
static const uint16_t WINDOW = 60;  // 0.6 s at 100 Hz
static const float RATE_SPREAD = 2.0f;
static const float ACC_SPREAD = 0.04f;
static const float GAIN = 0.004f;
static const float MAX_SLEW = 0.6f;  // dps per second
static const float DT = 0.01f;
static const float YAW_DECAY = 0.9998f;
static const float DEADZONE = 8.0f / 32.8f;
static const Vec3 LEVEL = {0, 0, 1};

// Deterministic jitter, so a run that fails fails the same way next time.
static uint32_t seed = 1;
static float noise(float amplitude) {
  seed = seed * 1664525u + 1013904223u;
  return ((float)((seed >> 8) & 0xFFFF) / 32768.0f - 1.0f) * amplitude;
}

static BiasTracker makeTracker() {
  return BiasTracker(WINDOW, RATE_SPREAD, ACC_SPREAD, GAIN, MAX_SLEW);
}

// Hold the gun still, with the hand tremor a real grip has.
static void holdStill(BiasTracker &t, const Vec3 &true_bias, int samples) {
  for (int i = 0; i < samples; i++) {
    const Vec3 rot = {true_bias.x + noise(0.3f), true_bias.y + noise(0.3f),
                      true_bias.z + noise(0.3f)};
    const Vec3 acc = {noise(0.01f), noise(0.01f), 1.0f + noise(0.01f)};
    t.update(rot, acc, DT);
  }
}

int main() {
  printf("gyro bias tracker, window %u, spread %.1f dps, gain %.4f\n\n", WINDOW,
         RATE_SPREAD, GAIN);

  // The reported symptom: boot calibration ran while the gun was moving, so
  // the stored bias is off by 1.5 dps. With a 0.9998 decay yaw settles at
  // about fifty times that, which is well off the side of a 70 deg screen.
  {
    const Vec3 true_bias = {0.2f, -5.4f, -0.4f};
    const Vec3 bad_cal = {0.2f, -5.4f, -0.4f + 1.5f};

    AttitudeFilter uncorrected(0.98f, YAW_DECAY, DEADZONE);
    for (int i = 0; i < 6000; i++) {  // a full minute
      const Vec3 rate = {0, 0, true_bias.z - bad_cal.z};
      uncorrected.update(LEVEL, rate, DT);
    }
    // Half a 70 deg screen is 35 deg, so this is already past the edge one
    // minute in, and still heading for its resting point of about 75 deg.
    if (fabsf(uncorrected.yaw()) > 35.0f) {
      printf("  ok    %-50s %8.3f deg\n",
             "a 1.5 dps calibration error drives yaw off screen",
             uncorrected.yaw());
    } else {
      printf("  FAIL  %-50s got %.3f, wanted past 35\n",
             "a 1.5 dps calibration error drives yaw off screen",
             uncorrected.yaw());
      failures++;
    }
    for (int i = 0; i < 24000; i++) {
      const Vec3 rate = {0, 0, true_bias.z - bad_cal.z};
      uncorrected.update(LEVEL, rate, DT);
    }
    near("and settles near fifty times the error", uncorrected.yaw(), -75.0f,
         3.0f);

    BiasTracker tracker = makeTracker();
    tracker.seed(bad_cal);
    AttitudeFilter corrected(0.98f, YAW_DECAY, DEADZONE);
    for (int i = 0; i < 6000; i++) {
      const Vec3 rot = {true_bias.x + noise(0.3f), true_bias.y + noise(0.3f),
                        true_bias.z + noise(0.3f)};
      const Vec3 acc = {noise(0.01f), noise(0.01f), 1.0f + noise(0.01f)};
      tracker.update(rot, acc, DT);
      corrected.update(acc, tracker.correct(rot), DT);
    }
    below("the tracker keeps yaw on target instead",
          fabsf(corrected.yaw()), 2.0f);
    near("and recovers the true bias", tracker.bias().z, true_bias.z, 0.2f);
  }

  // What actually came off the board: calibration ran while the gun was being
  // waved through 439 dps and recorded a Z bias of -27.2 dps. Easing away from
  // an error that size at the slew limit would take three quarters of a
  // minute of perfect stillness, so an untrusted seed is replaced outright.
  {
    const Vec3 measured_mid_swing = {18.647f, -6.356f, -27.202f};
    const Vec3 true_bias = {0.05f, -5.4f, -0.38f};

    BiasTracker eased = makeTracker();
    eased.seed(measured_mid_swing);  // trusted: the old behaviour
    holdStill(eased, true_bias, 1000);  // 10 s of perfect stillness
    if (fabsf(eased.bias().z - true_bias.z) > 5.0f) {
      printf("  ok    %-50s %8.3f\n",
             "easing cannot recover a mid-swing calibration", eased.bias().z);
    } else {
      printf("  FAIL  %-50s got %.3f, wanted still far from %.3f\n",
             "easing cannot recover a mid-swing calibration", eased.bias().z,
             true_bias.z);
      failures++;
    }

    BiasTracker snapped = makeTracker();
    snapped.seed(measured_mid_swing, /*trusted=*/false);
    is_true("an untrusted seed starts untrusted", !snapped.trusted());
    holdStill(snapped, true_bias, WINDOW + 2);
    near("one still window replaces it outright", snapped.bias().z,
         true_bias.z, 0.2f);
    is_true("and the snap is reported once", snapped.consumeSnap());
    is_true("only once", !snapped.consumeSnap());
    is_true("after which it is trusted", snapped.trusted());

    // Being trusted must mean the slow path again, or a later pan could
    // replace the estimate wholesale instead of leaking into it slowly.
    holdStill(snapped, {0, 0, true_bias.z + 10.0f}, WINDOW + 2);
    below("a trusted estimate is never snapped again",
          fabsf(snapped.bias().z - true_bias.z), 0.5f);
  }

  // How long the player has to wait for that recovery. Anything beyond a few
  // seconds of holding steady would be felt as the gun being broken.
  {
    BiasTracker tracker = makeTracker();
    tracker.seed({0, 0, 1.1f});
    const Vec3 true_bias = {0, 0, -0.4f};
    int settled_at = -1;
    for (int i = 0; i < 3000; i++) {
      holdStill(tracker, true_bias, 1);
      if (settled_at < 0 && fabsf(tracker.bias().z - true_bias.z) < 0.15f) {
        settled_at = i;
      }
    }
    is_true("recovery starts at all", settled_at >= 0);
    below("recovers a 1.5 dps error within 8 s", settled_at * DT, 8.0f);
  }

  // The tracker must not learn while the gun is being aimed, or it would
  // absorb the player's own movement and fight them.
  {
    BiasTracker tracker = makeTracker();
    const Vec3 start = {0, 0, -0.4f};
    tracker.seed(start);
    for (int i = 0; i < 1200; i++) {
      // A swing: rate well clear of the noise floor, gravity swinging with it.
      const float phase = i * DT * 2.0f;
      const Vec3 rot = {0, 0, 40.0f * sinf(phase)};
      const Vec3 acc = {sinf(phase) * 0.4f, 0, cosf(phase) * 0.9f};
      tracker.update(rot, acc, DT);
    }
    near("a swinging gun does not move the estimate", tracker.bias().z,
         start.z, 0.02f);
    is_true("and is not reported as still", !tracker.still());
  }

  // A slow steady tilt is the hard case: the rate barely varies, so the gyro
  // alone looks stationary. Gravity moving across the accelerometer axes is
  // the only thing that gives it away, and only if the axes are checked
  // separately -- the magnitude stays at exactly 1 g throughout.
  {
    BiasTracker tracker = makeTracker();
    tracker.seed({0, 0, 0});
    for (int i = 0; i < 1500; i++) {
      const float angle = i * DT * 6.0f / 57.2957795f;  // 6 dps tilt
      const Vec3 rot = {0, 6.0f + noise(0.2f), 0};
      const Vec3 acc = {-sinf(angle), 0, cosf(angle)};
      tracker.update(rot, acc, DT);
    }
    below("a slow steady tilt is not absorbed as bias",
          fabsf(tracker.bias().y), 1.0f);
  }

  // Yawing a level gun does not move gravity at all, so the accelerometer
  // cannot help and the gyro has to catch it. A real hand never holds a rate
  // steady, and that variation is the signal.
  {
    BiasTracker tracker = makeTracker();
    tracker.seed({0, 0, -0.4f});
    for (int i = 0; i < 1500; i++) {
      const Vec3 rot = {noise(0.4f), noise(0.4f), 14.0f + noise(2.5f)};
      const Vec3 acc = {noise(0.01f), noise(0.01f), 1.0f + noise(0.01f)};
      tracker.update(rot, acc, DT);
    }
    near("a hand-held yaw pan is not absorbed as bias", tracker.bias().z,
         -0.4f, 0.1f);
  }

  // And the case that cannot be detected even in principle: a yaw pan so
  // smooth it has no variation to find. Nothing rejects it, so the only
  // guarantee is the slew limit, which caps the damage at a known rate rather
  // than letting the estimate chase the pan.
  {
    BiasTracker tracker = makeTracker();
    tracker.seed({0, 0, 0});
    for (int i = 0; i < 500; i++) {  // 5 s of machine-smooth 10 dps yaw
      tracker.update({0, 0, 10.0f}, {0, 0, 1.0f}, DT);
    }
    // Without the limit the estimate reaches 8 dps here, chasing the pan.
    below("an undetectable yaw pan leaks no faster than the slew limit",
          fabsf(tracker.bias().z), MAX_SLEW * 5.0f + 0.1f);

    // ...and holding still afterwards undoes it, which is what makes the leak
    // a brief transient rather than a gun that needs restarting.
    holdStill(tracker, {0, 0, 0}, 1500);
    below("and holding still afterwards undoes it", fabsf(tracker.bias().z),
          0.15f);
  }

  // Thermal drift: the bias the board measured when cold is not the bias it
  // has ten minutes later.
  {
    BiasTracker tracker = makeTracker();
    tracker.seed({0, 0, -0.4f});
    for (int i = 0; i < 30000; i++) {  // five minutes
      const float drifted = -0.4f - 1.2f * (i / 30000.0f);
      holdStill(tracker, {0, 0, drifted}, 1);
    }
    near("tracks bias that drifts with temperature", tracker.bias().z, -1.6f,
         0.2f);
  }

  // Nothing may happen before the window has enough history to judge spread.
  {
    BiasTracker tracker = makeTracker();
    tracker.seed({0, 0, 5.0f});
    for (uint16_t i = 0; i < WINDOW - 1; i++) {
      const bool moved = tracker.update({0, 0, 0}, LEVEL, DT);
      if (moved) {
        printf("  FAIL  %-50s moved at sample %u\n",
               "no update before the window is full", i);
        failures++;
        break;
      }
    }
    near("estimate untouched until the window fills", tracker.bias().z, 5.0f,
         0.0001f);
  }

  printf("\n%s\n", failures ? "FAILURES" : "all bias tracker checks passed");
  return failures ? 1 : 0;
}
