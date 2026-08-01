# Roadmap — Gyro Gunfight

## Phase 0 — Kit bring‑up (done)
- [x] Detect ESP8266 over USB
- [x] Wire MPU on I2C
- [x] Stream accel / gyro / temp
- [x] Document hardware + flash firmware

## Phase 1 — Aim controller
- [ ] Calibrate gyro bias at rest
- [ ] Complementary / Madgwick filter → stable pitch/yaw
- [ ] Map aim to screen / virtual crosshair
- [ ] Deadzone + sensitivity curve

## Phase 2 — Local game loop
- [ ] Trigger input (button or IR)
- [ ] Hit / miss logic vs targets
- [ ] OLED or Serial HUD (ammo, HP, score)
- [ ] Simple single‑player range mode

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
