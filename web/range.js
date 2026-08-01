"use strict";

const ROUND_SECONDS = 60;
const MAG_SIZE = 6;
const RELOAD_MS = 900;
const WAVE_GAP_MS = 650;

// A deliberate barrel flick is far faster than aiming, so velocity separates
// the two cleanly. Only armed when the magazine is not already full.
const FLICK_DPS = 200;
const FLICK_WINDOW_MS = 180;

const canvas = document.getElementById("range");
const ctx = canvas.getContext("2d");

const ui = {
  dot: document.getElementById("dot"),
  link: document.getElementById("link"),
  rate: document.getElementById("rate"),
  overlay: document.getElementById("overlay"),
  overtitle: document.getElementById("overtitle"),
  oversub: document.getElementById("oversub"),
  summary: document.getElementById("summary"),
  sumscore: document.getElementById("sumscore"),
  sumacc: document.getElementById("sumacc"),
  sumwave: document.getElementById("sumwave"),
  sumstreak: document.getElementById("sumstreak"),
  timer: document.getElementById("timer"),
  wave: document.getElementById("wave"),
  left: document.getElementById("left"),
  mag: document.getElementById("mag"),
  reloadfill: document.getElementById("reloadfill"),
  magstate: document.getElementById("magstate"),
  score: document.getElementById("score"),
  hits: document.getElementById("hits"),
  shots: document.getElementById("shots"),
  acc: document.getElementById("acc"),
  streak: document.getElementById("streak"),
  pitch: document.getElementById("pitch"),
  yaw: document.getElementById("yaw"),
  roll: document.getElementById("roll"),
  trig: document.getElementById("trig"),
  sens: document.getElementById("sens"),
  sensval: document.getElementById("sensval"),
  smooth: document.getElementById("smooth"),
  smoothval: document.getElementById("smoothval"),
  center: document.getElementById("center"),
};

const aim = { pitch: 0, yaw: 0, roll: 0, trigger: 0, connected: false };
const offset = { pitch: 0, yaw: 0 };
const cursor = { x: 0.5, y: 0.5 };
const recoil = { x: 0, y: 0 };

const game = {
  state: "ready", // ready | playing | over
  endsAt: 0,
  remaining: ROUND_SECONDS,
  wave: 0,
  nextWaveAt: 0,
  ammo: MAG_SIZE,
  reloadingUntil: 0,
  score: 0,
  hits: 0,
  shots: 0,
  streak: 0,
  best: 0,
};

const targets = [];
const shotMarks = [];
const popups = [];
const pitchLog = [];

let sensitivity = 18;
let smoothing = 0.35;
let lastShots = null;
let packets = 0;
let muzzleFlash = 0;

function resize() {
  const rect = canvas.parentElement.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  canvas.width = Math.round(rect.width * dpr);
  canvas.height = Math.round(rect.height * dpr);
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
}

window.addEventListener("resize", resize);

function view() {
  const dpr = window.devicePixelRatio || 1;
  return { w: canvas.width / dpr, h: canvas.height / dpr };
}

function clamp01(v) {
  return Math.min(1, Math.max(0, v));
}

// Recoil moves the real aim point, not just the drawing, so rapid fire costs
// accuracy the same way it looks like it should.
function aimPoint() {
  const { w, h } = view();
  return {
    x: clamp01(cursor.x + recoil.x) * w,
    y: clamp01(cursor.y + recoil.y) * h,
  };
}

// --- round flow -----------------------------------------------------------

function startRound() {
  game.state = "playing";
  game.endsAt = performance.now() + ROUND_SECONDS * 1000;
  game.remaining = ROUND_SECONDS;
  game.wave = 0;
  game.nextWaveAt = 0;
  game.ammo = MAG_SIZE;
  game.reloadingUntil = 0;
  game.score = 0;
  game.hits = 0;
  game.shots = 0;
  game.streak = 0;
  game.best = 0;
  targets.length = 0;
  popups.length = 0;
  shotMarks.length = 0;
  nextWave();
  ui.overlay.classList.add("hidden");
  refreshStats();
}

function endRound() {
  game.state = "over";
  targets.length = 0;
  ui.sumscore.textContent = game.score;
  ui.sumacc.textContent = game.shots
    ? `${Math.round((game.hits / game.shots) * 100)}%`
    : "0%";
  ui.sumwave.textContent = Math.max(0, game.wave - 1);
  ui.sumstreak.textContent = game.best;
  ui.overtitle.textContent = "Round over";
  ui.oversub.textContent = "Pull the trigger to run it again.";
  ui.summary.hidden = false;
  ui.overlay.classList.remove("hidden");
}

function nextWave() {
  game.wave += 1;
  const count = Math.min(3 + Math.floor(game.wave / 2), 7);
  for (let i = 0; i < count; i += 1) spawnTarget();
  game.nextWaveAt = 0;
}

function spawnTarget() {
  const { w, h } = view();
  // Later waves are smaller and vanish sooner.
  const shrink = Math.max(0.45, 1 - (game.wave - 1) * 0.07);
  const radius = (15 + Math.random() * 20) * shrink;
  const life = Math.max(1700, 4200 - (game.wave - 1) * 260) + Math.random() * 900;
  targets.push({
    x: radius + Math.random() * (w - radius * 2),
    y: radius + h * 0.06 + Math.random() * (h * 0.8 - radius * 2),
    r: radius,
    born: performance.now(),
    life,
  });
}

// --- shooting -------------------------------------------------------------

function fire() {
  if (game.state !== "playing") {
    startRound();
    return;
  }

  const now = performance.now();
  if (now < game.reloadingUntil) return;

  if (game.ammo <= 0) {
    addPopup("EMPTY", aimPoint(), "#8996ab");
    return;
  }

  game.ammo -= 1;
  game.shots += 1;
  muzzleFlash = 1;

  // Resolve the shot before kicking, so recoil only spoils the *next* one.
  const { x, y } = aimPoint();
  recoil.y -= 0.055;
  recoil.x += (Math.random() - 0.5) * 0.02;

  let hitIndex = -1;
  for (let i = targets.length - 1; i >= 0; i -= 1) {
    const t = targets[i];
    if (Math.hypot(t.x - x, t.y - y) <= t.r) {
      hitIndex = i;
      break;
    }
  }

  if (hitIndex >= 0) {
    const t = targets[hitIndex];
    // Small targets and deep waves are worth more than big early ones.
    const points = Math.round(Math.max(20, 120 - t.r * 2) * (1 + (game.wave - 1) * 0.15));
    game.hits += 1;
    game.score += points;
    game.streak += 1;
    game.best = Math.max(game.best, game.streak);
    targets.splice(hitIndex, 1);
    shotMarks.push({ x, y, at: now, hit: true });
    addPopup(`+${points}`, { x: t.x, y: t.y }, "#3ddc84");
  } else {
    game.streak = 0;
    game.score = Math.max(0, game.score - 10);
    shotMarks.push({ x, y, at: now, hit: false });
  }

  if (game.ammo === 0) addPopup("RELOAD", { x, y: y + 34 }, "#ffc857");
  refreshStats();
}

function startReload() {
  if (game.state !== "playing") return;
  if (game.ammo >= MAG_SIZE) return;
  if (performance.now() < game.reloadingUntil) return;
  game.reloadingUntil = performance.now() + RELOAD_MS;
}

function addPopup(text, at, color) {
  popups.push({ text, x: at.x, y: at.y, at: performance.now(), color });
}

// --- input ----------------------------------------------------------------

function connect() {
  const source = new EventSource("/stream");

  source.onmessage = (event) => {
    const data = JSON.parse(event.data);
    packets += 1;
    aim.pitch = data.pitch;
    aim.yaw = data.yaw;
    aim.roll = data.roll;
    aim.trigger = data.trigger;
    aim.connected = data.connected;

    trackFlick(data.pitch);

    // The device counts debounced presses, so a dropped packet cannot lose or
    // duplicate a shot the way watching for a 0->1 edge would.
    const shots = data.shots ?? 0;
    if (lastShots === null || shots < lastShots) {
      lastShots = shots; // first packet, or the board rebooted
    } else if (shots > lastShots) {
      const pending = Math.min(shots - lastShots, 5);
      for (let i = 0; i < pending; i += 1) fire();
      lastShots = shots;
    }

    ui.dot.classList.toggle("live", data.connected);
    ui.link.textContent = data.connected ? data.source : "device offline";
  };

  source.onerror = () => {
    aim.connected = false;
    ui.dot.classList.remove("live");
    ui.link.textContent = "bridge unreachable";
  };
}

function trackFlick(pitch) {
  const now = performance.now();
  pitchLog.push({ t: now, pitch });
  while (pitchLog.length > 2 && now - pitchLog[0].t > FLICK_WINDOW_MS) {
    pitchLog.shift();
  }
  if (game.ammo >= MAG_SIZE || pitchLog.length < 2) return;

  const oldest = pitchLog[0];
  const dt = (now - oldest.t) / 1000;
  if (dt < 0.05) return;

  const dps = (pitch - oldest.pitch) / dt;
  if (dps < -FLICK_DPS) {
    startReload();
    pitchLog.length = 0;
  }
}

function recentre() {
  offset.pitch = aim.pitch;
  offset.yaw = aim.yaw;
}

// --- update / draw --------------------------------------------------------

function updateCursor() {
  const dy = aim.pitch - offset.pitch;
  const dx = aim.yaw - offset.yaw;

  // Half the sensitivity span maps to each edge of the screen.
  const targetX = 0.5 - dx / sensitivity;
  const targetY = 0.5 - dy / sensitivity;
  const k = 1 - smoothing;

  cursor.x += (clamp01(targetX) - cursor.x) * k;
  cursor.y += (clamp01(targetY) - cursor.y) * k;

  recoil.x *= 0.85;
  recoil.y *= 0.85;
}

function updateGame(now) {
  if (game.state !== "playing") return;

  game.remaining = Math.max(0, (game.endsAt - now) / 1000);
  if (game.remaining <= 0) {
    endRound();
    return;
  }

  if (game.reloadingUntil && now >= game.reloadingUntil) {
    game.reloadingUntil = 0;
    game.ammo = MAG_SIZE;
  }

  for (let i = targets.length - 1; i >= 0; i -= 1) {
    if (now - targets[i].born > targets[i].life) {
      targets.splice(i, 1);
      game.streak = 0;
      refreshStats();
    }
  }

  if (targets.length === 0) {
    if (!game.nextWaveAt) game.nextWaveAt = now + WAVE_GAP_MS;
    else if (now >= game.nextWaveAt) nextWave();
  }
}

function drawBackdrop(w, h) {
  ctx.clearRect(0, 0, w, h);

  ctx.strokeStyle = "rgba(120,150,200,0.07)";
  ctx.lineWidth = 1;
  const step = 48;
  ctx.beginPath();
  for (let x = 0; x <= w; x += step) {
    ctx.moveTo(x, 0);
    ctx.lineTo(x, h);
  }
  for (let y = 0; y <= h; y += step) {
    ctx.moveTo(0, y);
    ctx.lineTo(w, y);
  }
  ctx.stroke();

  ctx.strokeStyle = "rgba(120,150,200,0.16)";
  ctx.beginPath();
  ctx.moveTo(0, h * 0.5);
  ctx.lineTo(w, h * 0.5);
  ctx.moveTo(w * 0.5, 0);
  ctx.lineTo(w * 0.5, h);
  ctx.stroke();
}

function drawTargets(now) {
  for (const t of targets) {
    const age = now - t.born;
    const fade = 1 - Math.max(0, (age - t.life * 0.7) / (t.life * 0.3));
    ctx.globalAlpha = 0.25 + 0.75 * fade;

    ctx.beginPath();
    ctx.arc(t.x, t.y, t.r, 0, Math.PI * 2);
    ctx.fillStyle = "#ff5c39";
    ctx.fill();

    ctx.beginPath();
    ctx.arc(t.x, t.y, t.r * 0.62, 0, Math.PI * 2);
    ctx.fillStyle = "#0b0e14";
    ctx.fill();

    ctx.beginPath();
    ctx.arc(t.x, t.y, t.r * 0.28, 0, Math.PI * 2);
    ctx.fillStyle = "#ff5c39";
    ctx.fill();

    ctx.globalAlpha = 1;
  }
}

function drawShotMarks(now) {
  for (let i = shotMarks.length - 1; i >= 0; i -= 1) {
    const m = shotMarks[i];
    const age = now - m.at;
    if (age > 600) {
      shotMarks.splice(i, 1);
      continue;
    }
    const p = age / 600;
    ctx.globalAlpha = 1 - p;
    ctx.strokeStyle = m.hit ? "#3ddc84" : "#8996ab";
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.arc(m.x, m.y, 6 + p * 26, 0, Math.PI * 2);
    ctx.stroke();
    ctx.globalAlpha = 1;
  }
}

function drawPopups(now) {
  ctx.textAlign = "center";
  ctx.font = "600 15px ui-sans-serif, system-ui, sans-serif";
  for (let i = popups.length - 1; i >= 0; i -= 1) {
    const p = popups[i];
    const age = now - p.at;
    if (age > 750) {
      popups.splice(i, 1);
      continue;
    }
    ctx.globalAlpha = 1 - age / 750;
    ctx.fillStyle = p.color;
    ctx.fillText(p.text, p.x, p.y - age * 0.03);
    ctx.globalAlpha = 1;
  }
}

function drawCrosshair() {
  const { x, y } = aimPoint();
  const tilt = (aim.roll * Math.PI) / 180;
  const reloading = performance.now() < game.reloadingUntil;

  ctx.save();
  ctx.translate(x, y);
  ctx.rotate(tilt);

  if (muzzleFlash > 0) {
    ctx.globalAlpha = muzzleFlash * 0.5;
    ctx.fillStyle = "#ffd27a";
    ctx.beginPath();
    ctx.arc(0, 0, 26, 0, Math.PI * 2);
    ctx.fill();
    ctx.globalAlpha = 1;
    muzzleFlash = Math.max(0, muzzleFlash - 0.08);
  }

  let colour = "#e6ecf5";
  if (!aim.connected) colour = "#5b6373";
  else if (reloading) colour = "#ffc857";
  else if (game.ammo === 0 && game.state === "playing") colour = "#ff5c39";

  ctx.strokeStyle = colour;
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.arc(0, 0, 13, 0, Math.PI * 2);
  ctx.moveTo(-22, 0);
  ctx.lineTo(-6, 0);
  ctx.moveTo(6, 0);
  ctx.lineTo(22, 0);
  ctx.moveTo(0, -22);
  ctx.lineTo(0, -6);
  ctx.moveTo(0, 6);
  ctx.lineTo(0, 22);
  ctx.stroke();

  ctx.fillStyle = "#ff5c39";
  ctx.beginPath();
  ctx.arc(0, 0, 2.4, 0, Math.PI * 2);
  ctx.fill();
  ctx.restore();
}

// --- readouts -------------------------------------------------------------

function buildMag() {
  ui.mag.innerHTML = "";
  for (let i = 0; i < MAG_SIZE; i += 1) {
    const shell = document.createElement("div");
    shell.className = "shell";
    ui.mag.appendChild(shell);
  }
}

function refreshStats() {
  ui.score.textContent = game.score;
  ui.hits.textContent = game.hits;
  ui.shots.textContent = game.shots;
  ui.streak.textContent = game.best;
  ui.acc.textContent = game.shots
    ? `${Math.round((game.hits / game.shots) * 100)}%`
    : "—";
}

function refreshHud(now) {
  ui.timer.textContent = game.remaining.toFixed(1);
  ui.timer.classList.toggle("low", game.state === "playing" && game.remaining < 10);
  ui.wave.textContent = game.state === "playing" ? game.wave : "—";
  ui.left.textContent = game.state === "playing" ? targets.length : "—";

  const shells = ui.mag.children;
  for (let i = 0; i < shells.length; i += 1) {
    shells[i].classList.toggle("spent", i >= game.ammo);
  }

  const reloading = now < game.reloadingUntil;
  if (reloading) {
    const left = game.reloadingUntil - now;
    ui.reloadfill.style.width = `${(1 - left / RELOAD_MS) * 100}%`;
    ui.magstate.textContent = "Reloading…";
  } else {
    ui.reloadfill.style.width = "0%";
    if (game.ammo === 0) ui.magstate.textContent = "Empty — flick down to reload";
    else if (game.ammo < MAG_SIZE) ui.magstate.textContent = `${game.ammo} left`;
    else ui.magstate.textContent = "Full";
  }

  ui.pitch.textContent = `${(aim.pitch - offset.pitch).toFixed(1)}°`;
  ui.yaw.textContent = `${(aim.yaw - offset.yaw).toFixed(1)}°`;
  ui.roll.textContent = `${aim.roll.toFixed(1)}°`;
  ui.trig.textContent = aim.trigger ? "DOWN" : "up";
}

function frame() {
  const { w, h } = view();
  const now = performance.now();

  updateCursor();
  updateGame(now);

  drawBackdrop(w, h);
  drawTargets(now);
  drawShotMarks(now);
  drawPopups(now);
  drawCrosshair();
  refreshHud(now);

  requestAnimationFrame(frame);
}

// --- wiring ---------------------------------------------------------------

ui.sens.addEventListener("input", () => {
  sensitivity = Number(ui.sens.value);
  ui.sensval.textContent = sensitivity;
});

ui.smooth.addEventListener("input", () => {
  smoothing = Number(ui.smooth.value) / 100;
  ui.smoothval.textContent = smoothing.toFixed(2);
});

ui.center.addEventListener("click", recentre);
canvas.addEventListener("mousedown", fire);

window.addEventListener("keydown", (event) => {
  if (event.code === "Space") {
    event.preventDefault();
    fire();
  }
  if (event.code === "KeyR") startReload();
  if (event.code === "KeyC") recentre();
});

setInterval(() => {
  ui.rate.textContent = `${packets} Hz`;
  packets = 0;
}, 1000);

resize();
buildMag();
refreshStats();
connect();
frame();
