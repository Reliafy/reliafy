import test from "node:test";
import assert from "node:assert/strict";
import { fullscreenApi, hasOpenLayer, isFullScreenKey, isTyping, movePortalHost, portalHost } from "./fullScreen.js";
import { rbdSaveSnapshot, rbdSaveStatus } from "./rbdSaveState.js";

// A tiny stand-in for the DOM: enough for the portal host to move about.
function fakeDoc() {
  const make = (tag) => {
    const node = {
      tagName: tag, children: [], parentNode: null, style: {}, focused: 0,
      appendChild(c) {
        if (c.parentNode) c.parentNode.children.splice(c.parentNode.children.indexOf(c), 1);
        c.parentNode = node;
        node.children.push(c);
        return c;
      },
      contains(c) {
        for (let n = c; n; n = n.parentNode) if (n === node) return true;
        return false;
      },
      focus() { doc.activeElement = node; node.focused += 1; },
    };
    node.ownerDocument = null;
    return node;
  };
  const doc = { createElement: (t) => Object.assign(make(t.toUpperCase()), { ownerDocument: doc }) };
  doc.body = make("BODY");
  doc.activeElement = doc.body;
  return doc;
}

test("fullscreenApi: standard, webkit, or none (iPhone Safari)", () => {
  const std = { documentElement: { requestFullscreen() {} }, exitFullscreen() {}, fullscreenElement: "x" };
  assert.equal(fullscreenApi(std).event, "fullscreenchange");
  assert.equal(fullscreenApi(std).element(), "x");
  const wk = { documentElement: { webkitRequestFullscreen() {} }, webkitExitFullscreen() {}, webkitFullscreenElement: null };
  assert.equal(fullscreenApi(wk).event, "webkitfullscreenchange");
  assert.equal(fullscreenApi(wk).element(), null);
  assert.equal(fullscreenApi({ documentElement: {} }), null);
  assert.equal(fullscreenApi(null), null);
});

test("the portal host moves into the full-screen part and back, keeping focus", () => {
  const doc = fakeDoc();
  const host = portalHost(doc);
  assert.equal(host.parentNode, doc.body);
  assert.equal(host.style.display, "contents");
  assert.equal(portalHost(doc), host, "one host, made once");
  const part = doc.createElement("div");
  doc.body.appendChild(part);
  const field = doc.createElement("input");
  host.appendChild(field);
  field.focus();
  movePortalHost(part, doc);
  assert.equal(host.parentNode, part);
  assert.equal(field.focused, 2, "focus put back after the move");
  movePortalHost(null, doc);
  assert.equal(host.parentNode, doc.body);
});

test("Escape waits for an open dialog, list or menu", () => {
  const seen = [];
  const root = { querySelector: (sel) => (seen.push(sel), null) };
  assert.equal(hasOpenLayer(root), false);
  for (const s of [".overlay", ".sel-menu", ".ovm-menu:not([hidden])"]) assert.ok(seen[0].includes(s));
  assert.ok(seen[0].includes(":not(.rbd-valid-pop)"), "the validation check doesn't hold full screen");
  assert.equal(hasOpenLayer({ querySelector: () => ({}) }), true);
  assert.equal(hasOpenLayer(null), false);
});

test("F toggles full screen, but not while typing or with a modifier", () => {
  const key = (k, extra = {}) => ({ key: k, target: { tagName: "DIV" }, ...extra });
  assert.ok(isFullScreenKey(key("f")));
  assert.ok(isFullScreenKey(key("F")));
  assert.ok(!isFullScreenKey(key("g")));
  for (const mod of ["metaKey", "ctrlKey", "altKey", "repeat"]) assert.ok(!isFullScreenKey(key("f", { [mod]: true })));
  for (const tag of ["INPUT", "TEXTAREA", "SELECT"]) assert.ok(!isFullScreenKey(key("f", { target: { tagName: tag } })));
  assert.ok(isTyping({ target: { tagName: "DIV", isContentEditable: true } }));
  assert.ok(!isFullScreenKey(null));
});

test("save snapshot: the diagram, not its selection or sizes", () => {
  const nodes = [{ id: "c1", type: "component", position: { x: 10, y: 20 }, data: { label: "Pump" } }];
  const edges = [{ id: "e1", source: "input", target: "c1" }];
  const base = rbdSaveSnapshot({ nodes, edges, unit: "Hours", repairable: false });
  const viewOnly = rbdSaveSnapshot({
    nodes: nodes.map((n) => ({ ...n, selected: true, width: 160, height: 80, dragging: false, position: { x: 10.1, y: 20 } })),
    edges: edges.map((e) => ({ ...e, selected: true })),
    repairable: false,
    unit: "Hours",
  });
  assert.equal(viewOnly, base, "selecting or measuring changes nothing; key order doesn't matter");
  assert.notEqual(rbdSaveSnapshot({ nodes: [...nodes, { id: "c2", type: "component", position: { x: 0, y: 0 }, data: {} }], edges, unit: "Hours", repairable: false }), base);
  assert.notEqual(rbdSaveSnapshot({ nodes, edges: [], unit: "Hours", repairable: false }), base);
  assert.notEqual(rbdSaveSnapshot({ nodes: [{ ...nodes[0], position: { x: 300, y: 20 } }], edges, unit: "Hours", repairable: false }), base);
  assert.notEqual(rbdSaveSnapshot({ nodes, edges, unit: "Days", repairable: false }), base);
  assert.notEqual(rbdSaveSnapshot({ nodes: [{ ...nodes[0], data: { label: "Motor" } }], edges, unit: "Hours", repairable: false }), base);
});

test("save status says it in words", () => {
  assert.equal(rbdSaveStatus({ savedId: null, dirty: true }).text, "Not saved yet");
  assert.equal(rbdSaveStatus({ savedId: "a", dirty: false }).text, "Saved");
  assert.equal(rbdSaveStatus({ savedId: "a", dirty: true }).text, "Unsaved changes");
  assert.equal(rbdSaveStatus({ savedId: "s", readOnly: true, dirty: false }).text, "Read only");
  assert.match(rbdSaveStatus({ savedId: "s", readOnly: true, dirty: true }).title, /save a copy/);
});
