// The design system's CSS guard (docs/design-system/README.md, Guards):
// stylelint (.stylelintrc.json) bans hex, rgb() and hsl() colours, and px/rem
// for space, type size and radius, and z-index numbers, everywhere but
// tokens.css. What was there when the guard came in is counted in
// stylelint-baseline.json, file by file and rule by rule, so only new
// violations fail: a file may go down, never up.
//
//   npm run lint:css                 # from frontend/: fails on anything over the baseline
//   npm run lint:css -- --update     # rewrite the baseline (only after removing violations)
import { readFileSync, writeFileSync, existsSync } from "node:fs";
import { relative } from "node:path";
import { fileURLToPath } from "node:url";
import stylelint from "stylelint";

const root = fileURLToPath(new URL("..", import.meta.url));
const BASELINE = fileURLToPath(new URL("../stylelint-baseline.json", import.meta.url));
const update = process.argv.includes("--update");

const { results } = await stylelint.lint({ files: "src/**/*.css", cwd: root });
const counts = {};
const warnings = {};
for (const r of results) {
  const file = relative(root, r.source).split("\\").join("/");
  for (const w of r.warnings) {
    if (w.severity !== "error") continue;
    const key = `${file} ${w.rule}`;
    counts[key] = (counts[key] || 0) + 1;
    (warnings[key] ||= []).push(w);
  }
  for (const e of r.parseErrors || []) console.error(`${file}: ${e.text}`);
}
const sorted = Object.fromEntries(Object.entries(counts).sort(([a], [b]) => a.localeCompare(b)));

if (update) {
  writeFileSync(BASELINE, JSON.stringify(sorted, null, 1) + "\n");
  const total = Object.values(sorted).reduce((a, b) => a + b, 0);
  console.log(`wrote stylelint-baseline.json: ${total} known violations in ${Object.keys(sorted).length} file/rule pairs`);
  process.exit(0);
}

const baseline = existsSync(BASELINE) ? JSON.parse(readFileSync(BASELINE, "utf8")) : {};
let failed = 0;
let fixed = 0;
for (const [key, n] of Object.entries(sorted)) {
  const allowed = baseline[key] || 0;
  if (n <= allowed) continue;
  failed += n - allowed;
  const [file, rule] = key.split(" ");
  console.error(`\n${file}: ${n} ${rule} (the baseline allows ${allowed}). Use a token for the new one${n - allowed > 1 ? "s" : ""}:`);
  for (const w of warnings[key]) console.error(`  ${file}:${w.line}:${w.column}  ${w.text.replace(/ \([^)]*\)$/, "")}`);
}
for (const [key, n] of Object.entries(baseline)) if ((sorted[key] || 0) < n) fixed += n - (sorted[key] || 0);
if (failed) {
  console.error(`\n${failed} new design-system violation${failed > 1 ? "s" : ""} in CSS (docs/design-system/README.md, Guards).`);
  process.exit(1);
}
const total = Object.values(sorted).reduce((a, b) => a + b, 0);
console.log(`CSS design-system guard: no new violations (${total} known in the baseline${fixed ? `; ${fixed} fewer than it records, run \`npm run lint:css -- --update\`` : ""}).`);
