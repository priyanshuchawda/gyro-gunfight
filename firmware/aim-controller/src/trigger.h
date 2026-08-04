#pragma once
#include <stdint.h>

// Debounce for a tactile switch wired to ground.
//
// Deliberately free of Arduino calls: the interesting failures are switches
// chattering dozens of times in a couple of milliseconds, taps landing either
// side of the threshold, and presses spanning the millis() rollover. None of
// those can be produced by pressing a button on the bench, so the caller
// supplies the level and the clock and the host tests supply the nasty ones.
class TriggerDebouncer {
 public:
  explicit TriggerDebouncer(uint32_t debounce_ms) : debounce_ms_(debounce_ms) {}

  // Feed the raw level (true = pressed) and the current millisecond clock.
  // Returns true only on the sample where a fresh press is committed.
  //
  // Every raw transition restarts the timer, so a level has to hold still for
  // the whole window to count. That is what rejects chatter, and it is also
  // why a tap shorter than the window is dropped rather than delayed.
  bool update(bool raw, uint32_t now_ms) {
    if (raw != raw_last_) {
      raw_last_ = raw;
      changed_ms_ = now_ms;
      return false;
    }

    // Unsigned subtraction, so this stays correct across the 49-day rollover.
    if (raw != state_ && (uint32_t)(now_ms - changed_ms_) >= debounce_ms_) {
      state_ = raw;
      if (raw) {
        shots_++;
        return true;
      }
    }
    return false;
  }

  bool pressed() const { return state_; }

  // Monotonic, so a host that misses packets can still count by delta.
  uint32_t shots() const { return shots_; }

 private:
  uint32_t debounce_ms_;
  bool raw_last_ = false;
  bool state_ = false;
  uint32_t changed_ms_ = 0;
  uint32_t shots_ = 0;
};
