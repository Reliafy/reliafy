// tokens.css from the design system's tokens.json (docs/design-system).
//   node scripts/build-tokens.mjs           # from frontend/: writes src/tokens.css
// tokensSync.test.js checks the file matches, so a value is only ever
// changed in tokens.json.
import { readFileSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

export const TOKENS_JSON = fileURLToPath(new URL("../../docs/design-system/tokens.json", import.meta.url));
export const TOKENS_CSS = fileURLToPath(new URL("../src/tokens.css", import.meta.url));

const HEADER = `/* Reliafy design tokens (design system v2).
   Generated from docs/design-system/tokens.json by \`npm run tokens\`:
   change a value there, never here (tokensSync.test.js checks).
   - Ramps (neutral, blue, green, amber, red, teal, violet, pink; 50–950): the
     raw colours. Step N has the same lightness in every hue: 600 is the first
     text-safe step, 500 the first with 3:1, 700 coloured text on its own tint.
   - Roles (bg-*, border*, text*, accent*, success*, warning*, danger*, cat-*,
     chart-*): what rules use. Light is the default; [data-theme="dark"]
     remaps the roles onto the same ramps.
   - fs-N always goes with lh-N; space-N is N x 4px; one control height per size. */`;

const ref = (v) => {
  const m = /^\{(.+)\}$/.exec(v);
  return m ? `var(--${m[1]})` : v;
};

export function tokensCss(tokens) {
  const themes = tokens.color.themes.map((t) => t.id);
  const valueIn = (t, theme, i) => (typeof t.value === "string" ? (i === 0 ? t.value : null) : t.value[theme] ?? null);
  const out = [HEADER];
  themes.forEach((theme, i) => {
    out.push(`${i === 0 ? ":root, " : ""}[data-theme="${theme}"] {`);
    for (const family of ["color", "shadow"]) {
      for (const t of tokens[family].tokens) {
        const v = valueIn(t, theme, i);
        if (v != null) out.push(`  --${t.name}: ${ref(v)};`);
      }
    }
    out.push("}");
  });
  out.push(":root {");
  for (const family of ["spacing", "radius", "size", "fontSize", "lineHeight", "fontWeight"]) {
    for (const t of tokens[family]?.tokens || []) out.push(`  --${t.name}: ${t.value};`);
  }
  for (const [key, stack] of Object.entries(tokens.type.families)) out.push(`  --font-${key}: ${stack};`);
  out.push("}");
  return out.join("\n") + "\n";
}

if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) {
  writeFileSync(TOKENS_CSS, tokensCss(JSON.parse(readFileSync(TOKENS_JSON, "utf8"))));
  console.log(`wrote ${TOKENS_CSS}`);
}
