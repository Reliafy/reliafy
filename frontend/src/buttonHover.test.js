// Run with: node --test src/
// The default button hover must not outrank a button reset by one class.
// `button:hover:not(:disabled)` (0,2,1) beat every `.x:hover` (0,2,0), so a
// list row or title built on a <button> with `all: unset` turned solid blue
// under the pointer (the RCM function rows). The rule is written at no weight.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

const css = readFileSync(fileURLToPath(new URL("./index.css", import.meta.url)), "utf8");

test("the default button hover carries no weight of its own", () => {
  assert.match(css, /button:where\(:hover:not\(:disabled\)\)\s*\{\s*background: var\(--acc-d\);/);
  assert.doesNotMatch(css, /^button:hover:not\(:disabled\)/m);
});
