import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import {
  normaliseConfirm, deleteConfirm, removeSampleConfirm, removeSharedConfirm, deleteOrRemoveConfirm,
  normalisePrompt, renamePrompt, changedText, saveErrorText,
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

test("renamePrompt starts on the current name and names the action", () => {
  const p = normalisePrompt(renamePrompt({ kind: "dataset", name: "Pump bearings" }));
  assert.equal(p.title, "Rename this dataset");
  assert.equal(p.label, "Dataset name");
  assert.equal(p.value, "Pump bearings");
  assert.equal(p.confirmLabel, "Rename dataset");
  assert.equal(p.destructive, false);
  assert.equal(normalisePrompt(renamePrompt({ kind: "team" })).value, "");
  assert.throws(() => normalisePrompt({ title: "Rename", confirmLabel: "Rename" }), /needs a label/);
  assert.throws(() => normalisePrompt({ title: "Rename", label: "Name", confirmLabel: "OK" }), /Label the confirm button/);
});

test("changedText keeps only a new, non-blank name", () => {
  assert.equal(changedText(null, "a"), null);
  assert.equal(changedText("   ", "a"), null);
  assert.equal(changedText(" a ", "a"), null);
  assert.equal(changedText("  New name ", "a"), "New name");
  assert.equal(changedText("b", undefined), "b");
});

// The browser's own dialogs (confirm, alert, prompt) never come back: every
// question goes through ConfirmProvider. A bare confirm(...) is only allowed
// where `confirm` is the app's (from useConfirm, or passed in).
const stripComments = (src) => src.replace(/\/\*[\s\S]*?\*\//g, "").replace(/(^|[^:"'`])\/\/.*$/gm, "$1");

function nativeDialogCalls(src) {
  const code = stripComments(src);
  const found = [];
  const native = /\b(?:window|globalThis|self|top|parent)\s*\.\s*(confirm|alert|prompt)\s*\(/g;
  for (const m of code.matchAll(native)) found.push(m[0]);
  const bare = /(^|[^\w.$])(alert|prompt)\s*\(/gm;
  for (const m of code.matchAll(bare)) found.push(m[0].trim());
  const ownConfirm = /\bconst\s+confirm\s*=|function\s+confirm\s*\(|[({,]\s*confirm\s*[,})=]/.test(code);
  if (!ownConfirm) {
    for (const m of code.matchAll(/(^|[^\w.$])confirm\s*\(/gm)) found.push(m[0].trim());
  }
  return found;
}

test("the guard spots native dialogs and lets the app's own through", () => {
  assert.deepEqual(nativeDialogCalls('if (window.confirm("Sure?")) go();').length, 1);
  assert.deepEqual(nativeDialogCalls('const n = window.prompt("Name", x);').length, 1);
  assert.deepEqual(nativeDialogCalls('alert("Saved");').length, 1);
  assert.deepEqual(nativeDialogCalls("if (!confirm(`Delete ${x}?`)) return;").length, 1);
  assert.deepEqual(nativeDialogCalls("globalThis.alert(1)").length, 1);
  assert.deepEqual(nativeDialogCalls("const confirm = useConfirm();\nif (!(await confirm(req))) return;"), []);
  assert.deepEqual(nativeDialogCalls("// window.confirm is never used\nconst a = 1;"), []);
  assert.deepEqual(nativeDialogCalls('const url = "https://x/y"; // alert("x")'), []);
});

test("no browser confirm, alert or prompt anywhere in the app", () => {
  const offenders = [];
  const walk = (dir) => {
    for (const f of readdirSync(dir)) {
      const p = join(dir, f);
      if (statSync(p).isDirectory()) walk(p);
      else if (/\.(jsx?|mjs|tsx?)$/.test(f) && !/\.test\.[jt]s$/.test(f)) {
        const calls = nativeDialogCalls(readFileSync(p, "utf8"));
        if (calls.length) offenders.push(`${p}: ${calls.join(", ")}`);
      }
    }
  };
  walk(new URL(".", import.meta.url).pathname);
  assert.deepEqual(offenders, []);
});

test("a dialog that does the work itself: run and its pending words", () => {
  const run = async () => "id";
  const c = normaliseConfirm({ title: "Delete this function?", confirmLabel: "Delete function", run, pendingLabel: "Deleting…" });
  assert.equal(c.run, run);
  assert.equal(c.pendingLabel, "Deleting…");
  assert.equal(normalisePrompt({ title: "Add a function", label: "What must it do?", confirmLabel: "Add function", run }).pendingLabel, "Saving…");
  const plain = normaliseConfirm({ title: "Delete?", confirmLabel: "Delete it" });
  assert.equal("run" in plain, false);
  assert.equal("pendingLabel" in plain, false);
});

test("a save that didn't go through says so in plain words, never the raw error", () => {
  const offline = "Couldn't save. Check your connection and try again.";
  for (const m of ["Failed to fetch", "Load failed", "NetworkError when attempting to fetch resource.", "", undefined]) {
    assert.equal(saveErrorText(new TypeError(m)), offline, String(m));
  }
  assert.equal(saveErrorText(null), offline);
  assert.equal(saveErrorText(new Error("anything"), { offline: true }), offline);
  // The server's plain reason, as it said it.
  const refusal = Object.assign(new Error("Every function needs a description"), { status: 422 });
  assert.equal(saveErrorText(refusal), "Couldn't save. Every function needs a description.");
  assert.equal(saveErrorText(Object.assign(new Error("at most 4000 characters; this one is 5059."), { status: 422 })),
    "Couldn't save. At most 4000 characters; this one is 5059.");
  // FastAPI's list of what's wrong.
  const listed = Object.assign(new Error("[object Object]"), { status: 422, data: { detail: [{ msg: "Value error, text is too long" }] } });
  assert.equal(saveErrorText(listed), "Couldn't save. Text is too long.");
  // No reason worth showing: try again.
  assert.equal(saveErrorText(Object.assign(new Error("Request failed (500)"), { status: 500 })), "Couldn't save. Try again in a moment.");
  assert.equal(saveErrorText(Object.assign(new Error("Internal error"), { status: 503 })), "Couldn't save. Try again in a moment.");
  // Already in words: kept.
  assert.equal(saveErrorText(new Error("Couldn't save the decision")), "Couldn't save the decision.");
  // A delete says so.
  assert.equal(saveErrorText(new Error("Failed to fetch"), { what: "delete it" }), "Couldn't delete it. Check your connection and try again.");
});
