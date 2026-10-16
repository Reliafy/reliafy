// Mermaid's colours for the Admin page's Plan tab (AdminPlanTab.jsx), taken
// from the app's CSS tokens (index.css :root) so the charts match the app.
// The Gantt keeps the plan's legend readable:
//   not started  the accent blue, white text
//   active       a light accent tint with an accent outline, dark text
//   done         light grey with a grey outline, dark text
//   crit         red, white text (an active or done crit task keeps its own
//                fill with a red outline)
//   milestone    a diamond (mermaid's own), in its task's colours
//   sections     faint alternating bands; today a red line
// The app has no dark theme, so there's only this one palette.

// The tokens read, with index.css's values as the fallback.
export const TOKENS = {
  acc: "#2f6df6",
  "acc-d": "#2257d6",
  ink: "#14171c",
  muted: "#5f6670",
  line: "#e8e7e2",
  surf: "#ffffff",
  "surf-2": "#f6f5f1",
  danger: "#b91c1c",
  "cat-grey": "#6c727c",
};

// The tokens from the page's :root (a hex value, else the fallback).
export function readTokens(style = typeof document !== "undefined" ? getComputedStyle(document.documentElement) : null) {
  const out = { ...TOKENS };
  if (!style) return out;
  for (const name of Object.keys(TOKENS)) {
    const v = style.getPropertyValue(`--${name}`).trim();
    if (/^#[0-9a-f]{6}$/i.test(v)) out[name] = v.toLowerCase();
  }
  return out;
}

// `hex` mixed with white: amount 0 is white, 1 the colour itself.
export function tint(hex, amount) {
  const n = parseInt(hex.slice(1), 16);
  const ch = [16, 8, 0].map((s) => (n >> s) & 255);
  return "#" + ch.map((c) => Math.round(255 - (255 - c) * amount).toString(16).padStart(2, "0")).join("");
}

// `hex` darkened toward black by `amount` (0 to 1).
export function shade(hex, amount) {
  const n = parseInt(hex.slice(1), 16);
  const ch = [16, 8, 0].map((s) => (n >> s) & 255);
  return "#" + ch.map((c) => Math.round(c * (1 - amount)).toString(16).padStart(2, "0")).join("");
}

// mermaid.initialize({ theme: "base", themeVariables: ganttThemeVariables(t) })
export function ganttThemeVariables(t = TOKENS) {
  const white = "#ffffff";
  return {
    // Every diagram type: the app's ink, lines and a light accent fill.
    background: t.surf,
    primaryColor: tint(t.acc, 0.12),
    primaryBorderColor: t.acc,
    primaryTextColor: t.ink,
    secondaryColor: t["surf-2"],
    tertiaryColor: t["surf-2"],
    lineColor: t.muted,
    textColor: t.ink,
    titleColor: t.ink,
    // Gantt.
    taskBkgColor: t.acc,
    taskBorderColor: t["acc-d"],
    taskTextColor: white,
    taskTextLightColor: white,
    taskTextOutsideColor: t.ink,
    taskTextDarkColor: t.ink,
    taskTextClickableColor: t["acc-d"],
    activeTaskBkgColor: tint(t.acc, 0.14),
    activeTaskBorderColor: t.acc,
    doneTaskBkgColor: tint(t["cat-grey"], 0.32),
    doneTaskBorderColor: t["cat-grey"],
    critBkgColor: t.danger,
    critBorderColor: shade(t.danger, 0.3),
    // Mermaid draws section bands at 20% opacity.
    sectionBkgColor: tint(t["cat-grey"], 0.45),
    sectionBkgColor2: tint(t["cat-grey"], 0.45),
    altSectionBkgColor: t.surf,
    excludeBkgColor: t["surf-2"],
    gridColor: t.line,
    todayLineColor: t.danger,
    vertLineColor: t.muted,
  };
}
