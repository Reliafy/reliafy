// Pages added by optional extensions (backend/extensions.py).
//
// The server lists the pages this user may see (GET /api/extensions). Each is
// an ES module served only to those users, so it has to be fetched with the
// same credentials as any API call (the app sends Firebase ID tokens in a
// header, not cookies: a <script src> wouldn't be signed in). It's imported
// from a blob: URL, then its `mount(element, ctx)` draws the page:
//
//   mount(element, ctx) -> cleanup function | { unmount(), update(ctx) } | undefined
//
// `ctx` carries the host's React and ReactDOM (the module doesn't ship its
// own), the authenticated API helpers, navigation, theme tokens and the
// shared UI components; see buildContext() below. `update(ctx)` is called
// with a fresh context when the page's URL changes (back / forward, ?query).
//
// Pure helpers are exported for tests (extensions.test.js).

// The ctx shape's version: bumped on an incompatible change.
export const CONTEXT_VERSION = 1;

// Menu sections an extension page can sit in; anything else goes to "account".
export const SECTIONS = ["workspace", "account"];

export function sectionOf(mount) {
  return SECTIONS.includes(mount?.section) ? mount.section : "account";
}

// The mounts for one menu section, in the server's order.
export function mountsIn(mounts, section) {
  return (mounts || []).filter((m) => sectionOf(m) === section);
}

// The mount whose page `pathname` is in (its path, or anything under it).
export function mountForPath(mounts, pathname) {
  const p = (pathname || "").replace(/\/+$/, "") || "/";
  return (mounts || []).find((m) => p === m.path || p.startsWith(m.path + "/")) || null;
}

// What mount() returned, as { unmount, update }.
export function asHandle(result) {
  if (typeof result === "function") return { unmount: result, update: null };
  if (result && typeof result === "object") {
    return {
      unmount: typeof result.unmount === "function" ? result.unmount.bind(result) : null,
      update: typeof result.update === "function" ? result.update.bind(result) : null,
    };
  }
  return { unmount: null, update: null };
}

// The CSS custom properties extension pages may use (their current values):
// the design system's roles (tokens.css), plus the names before v2, which
// extensions written earlier still read. Each old name gives its new role's value.
export const THEME_TOKENS = [
  "--text", "--text-secondary", "--text-tertiary", "--text-disabled", "--text-on-fill",
  "--bg-canvas", "--bg-surface", "--bg-subtle", "--border", "--border-subtle", "--border-control",
  "--accent", "--accent-hover", "--accent-text", "--accent-subtle", "--accent-border",
  "--success", "--success-text", "--success-bg", "--warning", "--warning-text", "--warning-bg", "--warning-border",
  "--danger", "--danger-text", "--danger-bg", "--font-sans", "--font-mono", "--radius-md",
];
export const LEGACY_TOKENS = {
  "--ink": "--text", "--muted": "--text-secondary", "--subtle": "--text-tertiary", "--faint": "--text-disabled",
  "--line": "--border", "--line2": "--border-subtle", "--bg": "--bg-canvas", "--surf": "--bg-surface", "--surf-2": "--bg-subtle",
  "--acc": "--accent", "--acc-d": "--accent-hover", "--acc-line": "--accent-border", "--danger": "--danger",
  "--warn": "--warning", "--warn-bg": "--warning-bg", "--warn-line": "--warning-border", "--ok": "--success",
  "--on-fill": "--text-on-fill", "--mono": "--font-mono", "--r-sm": "--radius-md",
};

export function readTokens(style) {
  const out = {};
  const read = (name) => style?.getPropertyValue?.(name)?.trim();
  for (const name of THEME_TOKENS) {
    const v = read(name);
    if (v) out[name] = v;
  }
  for (const [old, now] of Object.entries(LEGACY_TOKENS)) {
    const v = out[now] || read(now);
    if (v) out[old] = v;
  }
  return out;
}

// Import a module's source (a fetch Response) through a blob: URL.
export async function importResponse(res) {
  if (!res.ok) {
    const err = new Error(res.status === 404 ? "This page isn't available." : `The page didn't load (${res.status}).`);
    err.status = res.status;
    throw err;
  }
  const code = await res.text();
  const url = URL.createObjectURL(new Blob([code], { type: "text/javascript" }));
  try {
    return await import(/* @vite-ignore */ url);
  } finally {
    URL.revokeObjectURL(url);
  }
}
