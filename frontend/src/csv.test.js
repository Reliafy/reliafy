// Run with: node --test src/
import { test } from "node:test";
import assert from "node:assert/strict";
import { csvCell, toCsv } from "./csv.js";

test("text that starts like a formula is kept as text", () => {
  assert.equal(csvCell("=SUM(A1:A2)"), "'=SUM(A1:A2)");
  assert.equal(csvCell("+1"), "'+1");
  assert.equal(csvCell("-2"), "'-2");
  assert.equal(csvCell("@cmd"), "'@cmd");
  assert.equal(csvCell("\t=1"), "'\t=1");
});

test("numbers and ordinary text are unchanged", () => {
  assert.equal(csvCell(-2.5), "-2.5");
  assert.equal(csvCell(0), "0");
  assert.equal(csvCell("Pump A"), "Pump A");
  assert.equal(csvCell(null), "");
  assert.equal(csvCell(undefined), "");
});

test("quoting still applies after the prefix", () => {
  assert.equal(csvCell('=HYPERLINK("x")'), `"'=HYPERLINK(""x"")"`);
  assert.equal(csvCell("a,b"), '"a,b"');
  assert.equal(csvCell("line\nbreak"), '"line\nbreak"');
});

test("rows join into CSV text", () => {
  assert.equal(toCsv([["item", "n"], ["=x", 3]]), "item,n\n'=x,3");
});
