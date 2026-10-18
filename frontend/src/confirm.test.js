import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import {
  normaliseConfirm, deleteConfirm, removeSampleConfirm, removeSharedConfirm, deleteOrRemoveConfirm,
} from "./confirm.js";

test("normaliseConfirm fills defaults", () => {
  const c = normaliseConfirm({ title: "Delete this diagram?", confirmLabel: "Delete diagram" });
  assert.equal(c.cancelLabel, "Cancel");
  assert.equal(c.body, "");
  assert.equal(c.destructive, true);
  assert.equal(normaliseConfirm({ title: "t", confirmLabel: "Leave team", destructive: false }).destructive, false);
});

test("normaliseConfirm refuses a vague or missing action label", () => {
  for (const confirmLabel of ["OK", "ok", "Yes", "Confirm", "", undefined]) {
    assert.throws(() => normaliseConfirm({ title: "Delete?", confirmLabel }), /Label the confirm button/);
  }
  assert.throws(() => normaliseConfirm({ confirmLabel: "Delete" }), /needs a title/);
});

test("deleteConfirm names the thing and says it can't be undone", () => {
  const c = deleteConfirm({ kind: "diagram", name: "Feed pump train" });
  assert.equal(c.title, "Delete this diagram?");
  assert.equal(c.confirmLabel, "Delete diagram");
  assert.match(c.body, /“Feed pump train” will be deleted\. This can't be undone\./);
  assert.match(deleteConfirm({ kind: "model", name: "x", extra: "and its saved results" }).body, /deleted, and its saved results\./);
});

test("removing a sample points at Settings, never 'you won't see it again'", () => {
  const c = removeSampleConfirm({ name: "Bearing life" });
  assert.equal(c.confirmLabel, "Remove sample");
  assert.match(c.body, /Settings › Sample data/);
  assert.doesNotMatch(c.body, /won't see it again/);
});

test("deleteOrRemoveConfirm picks by is_sample", () => {
  assert.equal(deleteOrRemoveConfirm({ name: "a", is_sample: true }, "model").confirmLabel, "Remove sample");
  assert.equal(deleteOrRemoveConfirm({ name: "a" }, "model").confirmLabel, "Delete model");
  assert.equal(deleteOrRemoveConfirm({ name: "a" }, "model", { name: "B" }).body.startsWith("“B”"), true);
  assert.equal(removeSharedConfirm({ name: "a" }).confirmLabel, "Remove from view");
  assert.equal(deleteOrRemoveConfirm({ name: "a", read_only: true }, "model").confirmLabel, "Remove from view");
});

// The browser's own dialog never comes back.
test("no window.confirm or window.alert in the app", () => {
  const offenders = [];
  const walk = (dir) => {
    for (const f of readdirSync(dir)) {
      const p = join(dir, f);
      if (statSync(p).isDirectory()) walk(p);
      else if (/\.(jsx?|mjs)$/.test(f) && !f.endsWith(".test.js")) {
        const src = readFileSync(p, "utf8");
        if (/\bwindow\.(confirm|alert)\s*\(/.test(src) || /(^|[^\w.])(confirm|alert)\s*\(\s*[`"']/m.test(src)) {
          offenders.push(p);
        }
      }
    }
  };
  walk(new URL(".", import.meta.url).pathname);
  assert.deepEqual(offenders, []);
});
