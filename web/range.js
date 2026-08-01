"use strict";

const canvas = document.getElementById("range");
const ctx = canvas.getContext("2d");

const ui = {
  dot: document.getElementById("dot"),
  link: document.getElementById("link"),
  rate: document.getElementById("rate"),
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

const stats = { score: 0, hits: 0, shots: 0, streak: 0, best: 0 };
const targets = [];

let sensitivity = 18;
let smoothing = 0.35;
let lastTrigger = 0;
let packets = 0;
let muzzleFlash = 0;
const shotMarks = [];

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

function spawnTarget() {
  const { w, h } = view();
  const radius = 16 + Math.random() * 22;
  targets.push({
    x: radius + Math.random() * (w - radius * 2),
    y: radius + Math.random() * (h * 0.75 - radius * 2) + h * 0.08,
    r: radius,
    born: performance.now(),
    life: 4200 + Math.random() * 2600,
    hit: 0,
  });
}

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

    if (data.trigger && !lastTrigger) shoot();
    lastTrigger = data.trigger;

    ui.dot.classList.toggle("live", data.connected);
    ui.link.textContent = data.connected ? data.source : "device offline";
  };

  source.onerror = () => {
    aim.connected = false;
    ui.dot.classList.remove("live");
    ui.link.textContent = "bridge unreachable";
  };
}

function recentre() {
  offset.pitch = aim.pitch;
  offset.yaw = aim.yaw;
}

function shoot() {
  const { w, h } = view();
  const x = cursor.x * w;
  const y = cursor.y * h;

  stats.shots += 1;
  muzzleFlash = 1;

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
    // Small, fast targets are worth more than big lazy ones.
    const points = Math.round(120 - t.r * 2);
    stats.hits += 1;
    stats.score += Math.max(20, points);
    stats.streak += 1;
    stats.best = Math.max(stats.best, stats.streak);
    t.hit = performance.now();
    targets.splice(hitIndex, 1);
    shotMarks.push({ x, y, at: performance.now(), hit: true });
    spawnTarget();
  } else {
    stats.streak = 0;
    stats.score = Math.max(0, stats.score - 10);
    shotMarks.push({ x, y, at: performance.now(), hit: false });
  }

  refreshStats();
}

function refreshStats() {
  ui.score.textContent = stats.score;
  ui.hits.textContent = stats.hits;
  ui.shots.textContent = stats.shots;
  ui.streak.textContent = stats.best;
  ui.acc.textContent = stats.shots
    ? `${Math.round((stats.hits / stats.shots) * 100)}%`
    : "—";
}

function updateCursor() {
  const dy = aim.pitch - offset.pitch;
  const dx = aim.yaw - offset.yaw;

  // Half the sensitivity span maps to each edge of the screen.
  const targetX = 0.5 - dx / sensitivity;
  const targetY = 0.5 - dy / sensitivity;
  const k = 1 - smoothing;

  cursor.x += (clamp01(targetX) - cursor.x) * k;
  cursor.y += (clamp01(targetY) - cursor.y) * k;
}

function clamp01(v) {
  return Math.min(1, Math.max(0, v));
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
  for (let i = targets.length - 1; i >= 0; i -= 1) {
    const t = targets[i];
    const age = now - t.born;
    if (age > t.life) {
      targets.splice(i, 1);
      stats.streak = 0;
      spawnTarget();
      continue;
    }

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

function drawCrosshair(w, h) {
  const x = cursor.x * w;
  const y = cursor.y * h;
  const tilt = (aim.roll * Math.PI) / 180;

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

  ctx.strokeStyle = aim.connected ? "#e6ecf5" : "#5b6373";
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

function frame() {
  const { w, h } = view();
  const now = performance.now();

  updateCursor();
  drawBackdrop(w, h);
  drawTargets(now);
  drawShotMarks(now);
  drawCrosshair(w, h);

  ui.pitch.textContent = `${(aim.pitch - offset.pitch).toFixed(1)}°`;
  ui.yaw.textContent = `${(aim.yaw - offset.yaw).toFixed(1)}°`;
  ui.roll.textContent = `${aim.roll.toFixed(1)}°`;
  ui.trig.textContent = aim.trigger ? "DOWN" : "up";

  requestAnimationFrame(frame);
}

ui.sens.addEventListener("input", () => {
  sensitivity = Number(ui.sens.value);
  ui.sensval.textContent = sensitivity;
});

ui.smooth.addEventListener("input", () => {
  smoothing = Number(ui.smooth.value) / 100;
  ui.smoothval.textContent = smoothing.toFixed(2);
});

ui.center.addEventListener("click", recentre);
canvas.addEventListener("mousedown", shoot);

window.addEventListener("keydown", (event) => {
  if (event.code === "Space") {
    event.preventDefault();
    shoot();
  }
  if (event.code === "KeyR") recentre();
});

setInterval(() => {
  ui.rate.textContent = `${packets} Hz`;
  packets = 0;
}, 1000);

resize();
for (let i = 0; i < 4; i += 1) spawnTarget();
refreshStats();
connect();
frame();
