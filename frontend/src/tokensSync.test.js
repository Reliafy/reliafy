// tokens.css is generated from docs/design-system/tokens.json: a value is
// changed there and `npm run tokens` rewrites the CSS. This fails when the
// CSS was edited by hand or the JSON changed without regenerating.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { TOKENS_CSS, TOKENS_JSON, tokensCss } from "../scripts/build-tokens.mjs";

test("src/tokens.css is what tokens.json generates (run `npm run tokens`)", () => {
  const want = tokensCss(JSON.parse(readFileSync(TOKENS_JSON, "utf8")));
  assert.equal(readFileSync(TOKENS_CSS, "utf8"), want);
});
