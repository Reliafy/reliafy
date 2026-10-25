// Run with: node --test src/basisUpload.test.js
import { test } from "node:test";
import assert from "node:assert/strict";
import { BASIS_FILE_MAX, BASIS_MAX, basisLength, decodeBasisFile, joinBasis, tidyBasis } from "./basisUpload.js";

const enc = (s) => new TextEncoder().encode(s);

test("a UTF-8 file becomes the text, with its BOM and Windows line endings tidied", () => {
  const bytes = new Uint8Array([0xef, 0xbb, 0xbf, ...enc("# Sums\r\n150 g ÷ 35,000 L  \r\n")]);
  assert.deepEqual(decodeBasisFile(bytes), { text: "# Sums\n150 g ÷ 35,000 L" });
  assert.equal(tidyBasis("a\rb"), "a\nb");
});

test("a file that is not UTF-8, or has NUL bytes, is refused in words", () => {
  assert.match(decodeBasisFile(new Uint8Array([0x66, 0xe9, 0x6f])).error, /isn't UTF-8/);
  assert.match(decodeBasisFile(new Uint8Array([0x25, 0x50, 0x00, 0x46])).error, /isn't a text file/);
});

test("too many bytes, or too many characters, is refused and never cut", () => {
  assert.match(decodeBasisFile(new Uint8Array(BASIS_FILE_MAX + 1)).error, /101 KB.*20,000 characters.*PDF/);
  const long = decodeBasisFile(enc("é".repeat(BASIS_MAX + 1)));
  assert.match(long.error, /20,001 characters.*at most 20,000/);
  assert.equal(decodeBasisFile(enc("é".repeat(BASIS_MAX))).text.length, BASIS_MAX);
});

test("adding below joins with a blank line; replacing, or an empty box, takes the file", () => {
  assert.equal(joinBasis("one", "two", "add"), "one\n\ntwo");
  assert.equal(joinBasis("one", "two", "replace"), "two");
  assert.equal(joinBasis("  ", "two", "add"), "two");
});

test("length is counted in characters as the server counts them", () => {
  assert.equal(basisLength("  😀a "), 2);
});
