#!/usr/bin/env node
/**
 * Static checks for the range page.
 *
 * Catches the two failures that a syntax check misses: a getElementById that
 * no element answers to, and CSS classes the script toggles but the stylesheet
 * never defines.
 */

"use strict";

const fs = require("fs");
const path = require("path");

const root = path.join(__dirname, "..", "web");
const html = fs.readFileSync(path.join(root, "index.html"), "utf8");
const js = fs.readFileSync(path.join(root, "range.js"), "utf8");

const problems = [];

const htmlIds = new Set([...html.matchAll(/\bid="([^"]+)"/g)].map((m) => m[1]));
const wantedIds = [...js.matchAll(/getElementById\("([^"]+)"\)/g)].map((m) => m[1]);

for (const id of wantedIds) {
  if (!htmlIds.has(id)) problems.push(`script looks up #${id}, which the page never defines`);
}

const cssClasses = new Set([...html.matchAll(/\.([a-zA-Z][\w-]*)\s*[,{]/g)].map((m) => m[1]));
const toggled = [...js.matchAll(/classList\.(?:toggle|add|remove)\("([^"]+)"/g)].map((m) => m[1]);

for (const cls of toggled) {
  if (!cssClasses.has(cls)) problems.push(`script toggles .${cls}, which the stylesheet never defines`);
}

if (!/<script src="range\.js">/.test(html)) {
  problems.push("index.html does not load range.js");
}

if (problems.length) {
  for (const p of problems) console.error(`FAIL ${p}`);
  process.exit(1);
}

console.log(`ok: ${wantedIds.length} element lookups and ${toggled.length} class toggles all resolve`);
