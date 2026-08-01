#!/usr/bin/env node
/**
 * Headless tests for the range game rules.
 *
 * Loads web/range.js into a vm context with the browser APIs stubbed and a
 * fake clock, so round flow, ammo, reload and the flick gesture can be
 * exercised without a display.
 */

"use strict";

const fs = require("fs");
const path = require("path");
const vm = require("vm");

let now = 1000;
const WIDTH = 1000;
const HEIGHT = 600;

function makeElement(id) {
  const children = [];
  const el = {
    id,
    textContent: "",
    hidden: false,
    style: {},
    value: "18",
    children,
    classList: {
      _set: new Set(),
      toggle(name, force) {
        const on = force === undefined ? !this._set.has(name) : force;
        if (on) this._set.add(name);
        else this._set.delete(name);
      },
      add(name) { this._set.add(name); },
      remove(name) { this._set.delete(name); },
      contains(name) { return this._set.has(name); },
    },
    addEventListener() {},
    appendChild(child) { children.push(child); },
    getBoundingClientRect: () => ({ width: WIDTH, height: HEIGHT }),
  };
  Object.defineProperty(el, "innerHTML", {
    set() { children.length = 0; },
    get() { return ""; },
  });
  return el;
}

const noopCtx = new Proxy(
  {},
  {
    get: (target, prop) => {
      if (prop in target) return target[prop];
      return () => {};
    },
    set: (target, prop, value) => {
      target[prop] = value;
      return true;
    },
  }
);

const elements = new Map();
function byId(id) {
  if (!elements.has(id)) {
    const el = makeElement(id);
    if (id === "range") {
      el.getContext = () => noopCtx;
      el.parentElement = makeElement("stage");
      el.width = WIDTH;
      el.height = HEIGHT;
    }
    elements.set(id, el);
  }
  return elements.get(id);
}

const sandbox = {
  console,
  Math,
  JSON,
  document: {
    getElementById: byId,
    createElement: () => makeElement("div"),
  },
  window: { addEventListener() {}, devicePixelRatio: 1 },
  performance: { now: () => now },
  requestAnimationFrame: () => {},
  setInterval: () => {},
  EventSource: class {
    constructor() {
      this.onmessage = null;
      this.onerror = null;
    }
  },
};
sandbox.globalThis = sandbox;

const context = vm.createContext(sandbox);
const source = fs.readFileSync(path.join(__dirname, "..", "web", "range.js"), "utf8");
vm.runInContext(source, context, { filename: "range.js" });

const get = (expr) => vm.runInContext(expr, context);
const run = (expr) => vm.runInContext(expr, context);

let failures = 0;
function check(label, actual, expected) {
  const ok = actual === expected;
  if (!ok) failures += 1;
  console.log(`${ok ? "pass" : "FAIL"}  ${label}${ok ? "" : `  (got ${actual}, want ${expected})`}`);
}

function checkTrue(label, actual) {
  check(label, Boolean(actual), true);
}

// Aim straight at a target we place ourselves, ignoring recoil drift.
function aimAtFirstTarget() {
  run("recoil.x = 0; recoil.y = 0;");
  const t = get("targets[0]");
  run(`cursor.x = ${t.x / WIDTH}; cursor.y = ${t.y / HEIGHT};`);
}

console.log("round flow");
check("starts in ready state", get("game.state"), "ready");
run("fire()");
check("trigger starts the round", get("game.state"), "playing");
check("first wave is wave 1", get("game.wave"), 1);
checkTrue("wave one spawned targets", get("targets.length") > 0);
check("starting the round does not spend a shot", get("game.shots"), 0);
check("magazine starts full", get("game.ammo"), 6);

console.log("\nshooting");
aimAtFirstTarget();
const targetsBefore = get("targets.length");
run("fire()");
check("hitting a target removes it", get("targets.length"), targetsBefore - 1);
check("hit counted", get("game.hits"), 1);
check("shot counted", get("game.shots"), 1);
check("ammo spent", get("game.ammo"), 5);
checkTrue("score awarded", get("game.score") > 0);

run("recoil.x = 0; recoil.y = 0; cursor.x = 0.02; cursor.y = 0.98;");
const scoreBeforeMiss = get("game.score");
run("fire()");
check("miss breaks the streak", get("game.streak"), 0);
checkTrue("miss costs score", get("game.score") < scoreBeforeMiss);

console.log("\nammo and reload");
run("while (game.ammo > 0) { recoil.x = 0; recoil.y = 0; fire(); }");
check("magazine empties", get("game.ammo"), 0);
const shotsAtEmpty = get("game.shots");
run("fire()");
check("firing on empty does not spend a shot", get("game.shots"), shotsAtEmpty);

run("startReload()");
checkTrue("reload is in progress", get("performance.now() < game.reloadingUntil"));
run("fire()");
check("cannot fire mid-reload", get("game.shots"), shotsAtEmpty);
now += 1000;
run("updateGame(performance.now())");
check("reload refills the magazine", get("game.ammo"), 6);

console.log("\nflick gesture");
run("game.ammo = 2; pitchLog.length = 0;");
// A slow aim adjustment must not be mistaken for a reload.
for (let i = 0; i <= 6; i += 1) {
  now += 30;
  run(`trackFlick(${20 - i * 1.5})`);
}
check("slow aiming does not reload", get("performance.now() < game.reloadingUntil"), false);

run("pitchLog.length = 0;");
for (let i = 0; i <= 6; i += 1) {
  now += 30;
  run(`trackFlick(${20 - i * 12})`);
}
checkTrue("fast downward flick starts a reload", get("performance.now() < game.reloadingUntil"));

run("game.ammo = 6; pitchLog.length = 0; game.reloadingUntil = 0;");
for (let i = 0; i <= 6; i += 1) {
  now += 30;
  run(`trackFlick(${20 - i * 12})`);
}
check("flick ignored when the magazine is full", get("performance.now() < game.reloadingUntil"), false);

console.log("\nwaves and timer");
run("targets.length = 0; game.nextWaveAt = 0;");
const waveBefore = get("game.wave");
run("updateGame(performance.now())");
check("clearing a wave schedules the next", get("game.wave"), waveBefore);
now += 1000;
run("updateGame(performance.now())");
check("next wave spawns after the gap", get("game.wave"), waveBefore + 1);
checkTrue("next wave has targets", get("targets.length") > 0);

now += 61000;
run("updateGame(performance.now())");
check("round ends when the timer runs out", get("game.state"), "over");
check("targets cleared at round end", get("targets.length"), 0);

run("fire()");
check("trigger restarts after a round", get("game.state"), "playing");
check("restart resets the score", get("game.score"), 0);
check("restart refills the magazine", get("game.ammo"), 6);

console.log(failures ? `\n${failures} check(s) failed` : "\nall checks passed");
process.exit(failures ? 1 : 0);
