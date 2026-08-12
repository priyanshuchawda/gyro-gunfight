# Roadmap — Gyro Gunfight

## Phase 0 — Kit bring-up (done)
- [x] Detect ESP8266 over USB
- [x] Wire MPU on I2C
- [x] Stream accel / gyro / temp
- [x] Document hardware + flash firmware

## Phase 1 — Aim controller (done)
- [x] Calibrate gyro bias at rest
- [x] Complementary filter → stable pitch/roll, decayed yaw
- [x] Deadzone + adjustable sensitivity
- [x] Runtime bias tracking while playing
- [x] Reject calibration measured mid-swing
- [x] Wire and debounce the physical trigger on `D5`

## Phase 2 — 3D drone range (done)
- [x] Fixed-camera light-gun view steered by the physical gun
- [x] Quadcopter drones at varying depth in a white test chamber
- [x] Shadow-casting lighting for depth perception
- [x] Hit feedback — tracers, debris, score pop, reticle ticks, tumbling kills
- [x] Miss feedback — wall impact marks
- [x] Direct serial input (no browser bridge hop)
- [x] `--simulate` mode for development without hardware
- [x] Self-test: reticle/raycast agreement + rendered pixel check

## Phase 3 — Polish
- [ ] Round timer, waves, ammo, reload gesture (from earlier prototype)
- [ ] OLED HUD on the gun itself (ammo, score)
- [ ] Sound

## Phase 4 — Dual / arena
- [ ] ESP8266 Wi-Fi transport (ESP-NOW or UDP)
- [ ] Two sticks, shared match state
- [ ] Round timer, score sync

## Phase 5 — Spectacle (optional)
- [ ] Nano + A4988 recoil / pan servo
- [ ] LCD scoreboard
- [ ] LED muzzle flash

## Non-goals (for now)
- Full FPS engine on the ESP
- Mag-based heading (module has no working AK8963)
- Browser-based game client (superseded by `range3d/`)
