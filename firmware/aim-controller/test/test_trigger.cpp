// Host tests for the trigger debounce. Build and run:
//
//   g++ -std=c++11 -Wall -Wextra -o /tmp/test_trigger
//       firmware/aim-controller/test/test_trigger.cpp && /tmp/test_trigger
//
// These drive the same header the firmware uses. The point is the cases the
// bench cannot stage on demand: chatter, taps either side of the threshold,
// and the millis() rollover.

#include "../src/trigger.h"

#include <cstdio>
#include <string>
#include <vector>

static int failures = 0;

static void check(const std::string &name, uint32_t got, uint32_t want) {
  if (got == want) {
    printf("  ok    %-46s %u\n", name.c_str(), got);
  } else {
    printf("  FAIL  %-46s got %u, want %u\n", name.c_str(), got, want);
    failures++;
  }
}

// Hold a level for a span of milliseconds, sampling every millisecond the way
// the firmware loop does.
static void hold(TriggerDebouncer &t, bool level, uint32_t ms, uint32_t &clock) {
  for (uint32_t i = 0; i < ms; i++) {
    t.update(level, clock);
    clock++;
  }
}

static const uint32_t DEBOUNCE_MS = 25;

// A clean press of a given length, then a long release.
static void clean_press(TriggerDebouncer &t, uint32_t press_ms, uint32_t &clock) {
  hold(t, true, press_ms, clock);
  hold(t, false, 100, clock);
}

int main() {
  printf("trigger debounce, window = %u ms\n\n", DEBOUNCE_MS);

  {
    TriggerDebouncer t(DEBOUNCE_MS);
    uint32_t clock = 0;
    hold(t, false, 50, clock);
    check("idle switch fires nothing", t.shots(), 0);
  }

  {
    TriggerDebouncer t(DEBOUNCE_MS);
    uint32_t clock = 0;
    clean_press(t, 100, clock);
    check("one clean 100 ms press", t.shots(), 1);
  }

  {
    // Forty transitions inside three milliseconds, which is what a cheap
    // tactile switch actually does on make. Pressing by hand cannot stage this.
    TriggerDebouncer t(DEBOUNCE_MS);
    uint32_t clock = 0;
    hold(t, false, 50, clock);
    for (int i = 0; i < 40; i++) {
      t.update(i % 2 == 0, clock);
      if (i % 13 == 12) clock++;  // the whole burst spans ~3 ms
    }
    hold(t, true, 100, clock);
    hold(t, false, 100, clock);
    check("40 bounces on make still count once", t.shots(), 1);
  }

  {
    // Counting shots cannot tell a working timer reset from a missing one:
    // both land on a single shot. What separates them is when the press
    // commits, because the window has to run from the last bounce and not the
    // first. Without this check, deleting the reset passes every other test.
    TriggerDebouncer t(DEBOUNCE_MS);
    uint32_t clock = 0;
    hold(t, false, 50, clock);

    uint32_t last_bounce = 0;
    for (int i = 0; i < 40; i++) {
      t.update(i % 2 == 0, clock);
      last_bounce = clock;
      if (i % 13 == 12) clock++;
    }

    uint32_t commit = 0;
    for (uint32_t i = 0; i < 100; i++) {
      if (t.update(true, clock)) commit = clock;
      clock++;
    }
    check("window runs from the last bounce, not the first",
          commit >= last_bounce + DEBOUNCE_MS ? 1 : 0, 1);
  }

  {
    // Chatter on release must not invent a second shot.
    TriggerDebouncer t(DEBOUNCE_MS);
    uint32_t clock = 0;
    hold(t, true, 100, clock);
    for (int i = 0; i < 30; i++) {
      t.update(i % 2 == 1, clock);
      if (i % 10 == 9) clock++;
    }
    hold(t, false, 100, clock);
    check("chatter on release adds no shot", t.shots(), 1);
  }

  {
    // The documented cost of the window: anything shorter is dropped, not
    // delayed. These two pin the boundary from both sides.
    TriggerDebouncer t(DEBOUNCE_MS);
    uint32_t clock = 0;
    clean_press(t, DEBOUNCE_MS - 1, clock);
    check("tap 1 ms under the window is dropped", t.shots(), 0);
  }

  {
    TriggerDebouncer t(DEBOUNCE_MS);
    uint32_t clock = 0;
    clean_press(t, DEBOUNCE_MS + 1, clock);
    check("tap 1 ms over the window registers", t.shots(), 1);
  }

  {
    TriggerDebouncer t(DEBOUNCE_MS);
    uint32_t clock = 0;
    hold(t, true, 5000, clock);
    check("a 5 s hold is one shot, not a repeat", t.shots(), 1);
  }

  {
    // Fast trigger finger: five deliberate taps in about half a second.
    TriggerDebouncer t(DEBOUNCE_MS);
    uint32_t clock = 0;
    for (int i = 0; i < 5; i++) {
      hold(t, true, 50, clock);
      hold(t, false, 50, clock);
    }
    check("five rapid taps count five", t.shots(), 5);
  }

  {
    // A switch that never settles must never commit.
    TriggerDebouncer t(DEBOUNCE_MS);
    uint32_t clock = 0;
    for (int i = 0; i < 500; i++) {
      t.update(i % 2 == 0, clock);
      clock++;
    }
    check("a switch that never settles fires nothing", t.shots(), 0);
  }

  {
    // millis() wraps every 49.7 days. A press straddling the wrap must not be
    // swallowed by the subtraction going negative.
    TriggerDebouncer t(DEBOUNCE_MS);
    uint32_t clock = 0xFFFFFFF0u;  // 16 ms before the wrap
    hold(t, false, 8, clock);
    hold(t, true, 100, clock);     // starts pre-wrap, commits post-wrap
    hold(t, false, 100, clock);
    check("press across the millis() rollover", t.shots(), 1);
  }

  {
    // pressed() is the live level; shots() is the cumulative count.
    TriggerDebouncer t(DEBOUNCE_MS);
    uint32_t clock = 0;
    hold(t, true, 100, clock);
    check("pressed() true while held", t.pressed() ? 1 : 0, 1);
    hold(t, false, 100, clock);
    check("pressed() false after release", t.pressed() ? 1 : 0, 0);
    check("shots() stays at 1 after release", t.shots(), 1);
  }

  printf("\n%s\n", failures ? "FAILURES" : "all trigger checks passed");
  return failures ? 1 : 0;
}
