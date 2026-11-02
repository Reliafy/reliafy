import test from "node:test";
import assert from "node:assert/strict";
import { safetyStarter } from "./rbdSafetyStarter.js";

test("the safety starter: sensors 1oo2, logic, final element, in safety mode", () => {
  const { graph, starter, name } = safetyStarter();
  assert.equal(starter, "safety");
  assert.match(name, /Safety function/);
  assert.equal(graph.repairable, true);
  assert.equal(graph.safety_function, true);
  assert.equal(graph.target_sil, 2);
  const blocks = graph.nodes.filter((n) => n.type === "component");
  assert.equal(blocks.length, 4);
  for (const b of blocks) {
    assert.equal(b.data.inspection.interval, 8760, "proof-tested yearly");
    assert.equal(b.data.instant_repair, true);
    assert.equal(b.data.model.distribution_id, "exponential");
  }
  // The transmitters vote 1oo2 (both feed the logic solver) and share a common cause.
  const into = (id) => graph.edges.filter((e) => e.target === id).map((e) => e.source).sort();
  assert.deepEqual(into("c3"), ["c1", "c2"]);
  assert.deepEqual(graph.ccf_groups[0].members, ["c1", "c2"]);
  assert.ok(graph.ccf_groups[0].beta > 0 && graph.ccf_groups[0].beta < 1);
  // Every block lies on a path from Input to Output.
  assert.deepEqual(into("output"), ["c4"]);
  assert.deepEqual(into("c4"), ["c3"]);
});

test("the starter card leads with plain words; the standard's terms come after", async () => {
  const { readFileSync } = await import("node:fs");
  const src = readFileSync(new URL("./components/RbdSafetyStarter.jsx", import.meta.url), "utf8");
  const card = src.slice(src.indexOf("<SectionStarter"));
  const title = card.match(/title="([^"]*)"/)[1];
  assert.doesNotMatch(title, /1oo|PFD|SIL|IEC/, "the card's title is plain");
  const body = card.slice(card.indexOf("body="), card.indexOf("terms="));
  assert.match(body, /either one can trip/, "says what the voting means in words");
  assert.doesNotMatch(body, /1oo|PFD|SIL|IEC/, "no standard's terms in the plain description");
  const terms = card.match(/terms="([^"]*)"/)?.[1] || "";
  for (const term of ["1oo2", "PFDavg", "SIL", "IEC 61511"]) assert.ok(terms.includes(term), `${term} on the quieter line`);
});
