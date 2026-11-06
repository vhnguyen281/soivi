// Run with: npm test
import assert from "node:assert/strict";
import { test } from "node:test";

import { complete, profile, QUESTIONS, type Answers } from "../lib/riskProfile.ts";

function all(score: number, overrides: Answers = {}): Answers {
  return { ...Object.fromEntries(QUESTIONS.map((q) => [q.id, score])), ...overrides };
}

test("every question has five options and a dimension", () => {
  assert.equal(QUESTIONS.length, 9);
  for (const q of QUESTIONS) assert.equal(q.options.length, 5, q.id);
  assert.ok(QUESTIONS.some((q) => q.dimension === "ability") && QUESTIONS.some((q) => q.dimension === "willingness"));
});

test("the lower of ability and willingness decides", () => {
  assert.equal(profile(all(5)).level, 5);
  const keen = profile(all(5, { emergency: 1, income: 1, share: 1, debt: 2 }));
  assert.ok(keen.ability < keen.willingness);
  assert.equal(keen.level, keen.ability);
  assert.ok(keen.notes.includes("capacity_limits"));
});

test("a short horizon caps the level", () => {
  const p = profile(all(5, { horizon: 1 }));
  assert.equal(p.level, 1);
  assert.ok(p.notes.includes("short_horizon"));
  assert.equal(profile(all(5, { horizon: 2 })).level, 2);
});

test("behavioural notes", () => {
  assert.ok(profile(all(4, { fall: 1, choice: 5 })).notes.includes("loss_aversion"));
  assert.ok(profile(all(3, { experience: 1, self: 5 })).notes.includes("overconfidence"));
  assert.deepEqual(profile(all(3)).notes, []);
});

test("incomplete answers are detected and refused", () => {
  const half: Answers = { horizon: 3 };
  assert.equal(complete(half), false);
  assert.throws(() => profile(half));
  assert.equal(complete(all(2)), true);
});
