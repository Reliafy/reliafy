import { test } from "node:test";
import assert from "node:assert/strict";
import { twinOfferText, twinWrites, twinsToOffer } from "./taskTwins.js";

const OUT = {
  twins: [
    { id: "t2", interval: 12000, unit: "hours", position: { name: "Pump B" } },
    { id: "t3", interval: 14800, unit: "hours", position: { name: "Pump C" } },
  ],
};

test("only twins at another interval are offered", () => {
  const offer = twinsToOffer(OUT, 14800, "hours");
  assert.deepEqual(offer.map((t) => t.id), ["t2"]);
  assert.equal(twinOfferText("Replace the seal", offer, 14800, "hours"),
    "Pump B has “Replace the seal” every 12,000 hours. Give it every 14,800 hours too?");
  assert.deepEqual(twinWrites(offer, 14800, "hours"), [{ id: "t2", body: { interval: 14800, unit: "hours" } }]);
});

test("a change of unit counts as different; none left means no offer", () => {
  assert.equal(twinsToOffer(OUT, 14800, "days").length, 2);
  assert.equal(twinOfferText("x", [], 1, "days"), "");
  assert.match(twinOfferText("Grease", twinsToOffer(OUT, 3, "months"), 3, "months"), /^2 identical positions have “Grease” at another interval \(Pump B: 12,000 hours; Pump C: 14,800 hours\)\. Give them every 3 months too\?$/);
});
