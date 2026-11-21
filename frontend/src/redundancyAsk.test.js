import { test } from "node:test";
import assert from "node:assert/strict";
import { arrangementsFrom, askProblem, setKey, setNames } from "./redundancyAsk.js";

const pumps = { position_ids: ["a", "b"], names: ["Pump set 1", "Pump set 2"] };
const bearings = { position_ids: ["w1", "w2", "w3", "w4"], names: ["Wheel 1", "Wheel 2", "Wheel 3", "Wheel 4"] };

test("every look-alike set must be answered before building", () => {
  assert.equal(askProblem([pumps], {}), "Say how Pump set 1 and Pump set 2 work together.");
  assert.equal(askProblem([pumps], { [setKey(pumps)]: { how: "standby" } }), null);
  assert.equal(setNames(bearings), "Wheel 1, Wheel 2, Wheel 3 and Wheel 4");
});

test("answers become the build's arrangements, k kept within 1 to n - 1", () => {
  const got = arrangementsFrom([pumps, bearings], {
    [setKey(pumps)]: { how: "series" }, [setKey(bearings)]: { how: "parallel", k: 3 } });
  assert.deepEqual(got, [{ position_ids: ["a", "b"], how: "series" },
                         { position_ids: ["w1", "w2", "w3", "w4"], how: "parallel", k: 3 }]);
  assert.deepEqual(arrangementsFrom([pumps], { [setKey(pumps)]: { how: "parallel", k: 9 } }),
                   [{ position_ids: ["a", "b"], how: "parallel", k: 1 }]);
});
