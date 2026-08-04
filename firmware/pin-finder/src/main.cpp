// Finds which pin the trigger is actually wired to.
//
// Every candidate gets an internal pull-up, so a button wired to ground reads
// LOW while held. Each pin latches the fact that it was ever seen low and the
// summary reprints every second, so the press and the reading do not have to
// happen at the same moment.

#include <Arduino.h>

struct Candidate {
  uint8_t gpio;
  const char *label;
  bool ever_low;
  uint32_t presses;
  bool last_low;
};

// D1 and D2 are left out: the MPU sits on them and I2C traffic would look
// like button presses. D0 has no usable internal pull-up.
static Candidate pins[] = {
    {0, "D3", false, 0, false},  {2, "D4", false, 0, false},
    {14, "D5", false, 0, false}, {12, "D6", false, 0, false},
    {13, "D7", false, 0, false}, {15, "D8", false, 0, false},
};
static const size_t COUNT = sizeof(pins) / sizeof(pins[0]);

static uint32_t last_report = 0;

void setup() {
  Serial.begin(115200);
  delay(400);
  for (size_t i = 0; i < COUNT; i++) pinMode(pins[i].gpio, INPUT_PULLUP);

  Serial.println();
  Serial.println("# pin finder - press and hold the trigger a few times");
  Serial.println("# watching D3 D4 D5 D6 D7 D8");
}

void loop() {
  for (size_t i = 0; i < COUNT; i++) {
    const bool low = digitalRead(pins[i].gpio) == LOW;
    if (low && !pins[i].last_low) {
      pins[i].presses++;
      pins[i].ever_low = true;
    }
    pins[i].last_low = low;
  }
  delay(5);

  const uint32_t now = millis();
  if (now - last_report < 1000) return;
  last_report = now;

  String live = "";
  String found = "";
  for (size_t i = 0; i < COUNT; i++) {
    if (pins[i].last_low) {
      live += String(pins[i].label) + " ";
    }
    if (pins[i].ever_low) {
      found += String(pins[i].label) + "=" + String(pins[i].presses) + " ";
    }
  }
  Serial.printf("# now_low[ %s] ever_low[ %s]\n", live.c_str(), found.c_str());
}
