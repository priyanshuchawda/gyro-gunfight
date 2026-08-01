# Roadmap — Gyro Gunfight

## Phase 0 — Kit bring‑up (done)
- [x] Detect ESP8266 over USB
- [x] Wire MPU on I2C
- [x] Stream accel / gyro / temp
- [x] Document hardware + flash firmware

## Phase 1 — Aim controller (done)
- [x] Calibrate gyro bias at rest
- [x] Complementary filter → stable pitch/roll, decayed yaw
- [x] Map aim to screen / virtual crosshair
- [x] Deadzone + adjustable sensitivity and smoothing
- [x] Serial → browser bridge and range demo

## Phase 2 — Local game loop
- [x] Hit / miss logic vs targets, score and accuracy
- [x] Wire the physical trigger button on `D5`
- [x] Debounce the trigger and count shots losslessly
- [x] Recoil kick that moves the real aim point
- [x] Target spawn waves and a round timer
- [x] Ammo and reload gesture (flick the barrel down)
- [ ] OLED HUD on the gun itself (ammo, HP, score)
- [ ] Sound and hit feedback

## Phase 3 — Dual / arena
- [ ] ESP8266 Wi‑Fi transport (ESP‑NOW or UDP)
- [ ] Two sticks, shared match state
- [ ] Round timer, score sync

## Phase 4 — Spectacle (optional)
- [ ] Nano + A4988 recoil / pan servo
- [ ] LCD scoreboard
- [ ] Sound / LED muzzle flash

## Non‑goals (for now)
- Full FPS engine on the ESP
- Mag‑based heading (module has no working AK8963)
