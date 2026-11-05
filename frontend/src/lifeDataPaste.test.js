// Run with: node --test src/
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  parsePastedValues, addMissingFlags, lineRanges, isUnitless, UNITLESS,
} from "./lifeData.js";

const MIXED = "100\n200\n300\n400\n500\n600\n700\n1200 1\n1300 1\n1400 1";

test("bare times mixed with flagged lines say which lines are which, and how to fix it", () => {
  assert.throws(() => parsePastedValues(MIXED), (err) => {
    assert.equal(err.message,
      "Lines 1–7 have one value, but lines 8–10 have two (a time and a censor flag). " +
      "Every line needs the same shape: give each line a flag (0 = failed, 1 = still running), or remove the flags.");
    assert.equal(err.fix, "add-flags");
    assert.deepEqual(err.lines, [1, 2, 3, 4, 5, 6, 7]);
    assert.doesNotMatch(err.message, /one value per line, or two per line/);
    return true;
  });
});

test("line numbers count blank lines and the header as the user sees them", () => {
  assert.throws(() => parsePastedValues("time\n100\n\n200 1\n300"), (err) => {
    assert.match(err.message, /^Lines 2 and 5 have one value, but line 4 has two/);
    assert.deepEqual(err.lines, [2, 5]);
    return true;
  });
});

test("Add 0 (failed) fills only the lines without a flag, then the paste parses", () => {
  const fixed = addMissingFlags(MIXED);
  assert.equal(fixed.split("\n")[0], "100 0");
  assert.equal(fixed.split("\n")[7], "1200 1");
  const parsed = parsePastedValues(fixed);
  assert.equal(parsed.cols, 2);
  assert.equal(parsed.rows, 10);
  assert.match(parsed.csv, /^time,censored\n100,0\n/);
  assert.match(parsed.csv, /1400,1\n$/);
  // A header line, blank lines and comma pastes keep their shape.
  assert.equal(addMissingFlags("time\n100\n\n200 1"), "time\n100 0\n\n200 1");
  assert.equal(addMissingFlags("100\n200,1"), "100,0\n200,1");
});

test("other mixed shapes name both lines and the rule", () => {
  assert.throws(() => parsePastedValues("100 200\n300"),
    /Line 2 has 1 value but line 1 has 2\. Put one time on each line, or a time and a censor flag/);
});

test("plain pastes still work", () => {
  assert.equal(parsePastedValues("312\n420\n506").csv, "time\n312\n420\n506\n");
  assert.equal(parsePastedValues("120 0\n340 1").csv, "time,censored\n120,0\n340,1\n");
  assert.equal(parsePastedValues("1, 2, 3\n4, 5, 6").rows, 6);
  assert.throws(() => parsePastedValues("120 0\n340 7"), /Line 2: censoring flag "7"/);
  assert.throws(() => parsePastedValues(""), /Paste at least a few values/);
});

test("lineRanges reads like a sentence", () => {
  assert.equal(lineRanges([3]), "line 3");
  assert.equal(lineRanges([1, 2, 3, 5]), "lines 1–3 and 5");
  assert.equal(lineRanges([1, 3, 5, 7, 9]), "lines 1, 3, 5 and 2 more");
});

test("No unit is an explicit choice; a blank unit is just not chosen", () => {
  assert.equal(isUnitless(UNITLESS), true);
  assert.equal(isUnitless(""), false); // not chosen yet is not "no unit"
  assert.equal(isUnitless("Hours"), false);
});
