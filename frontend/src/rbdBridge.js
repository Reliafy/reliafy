// A tiny bridge so the AI assistant (mounted in the app shell) can read and
// drive the live RBD builder canvas (mounted on /rbds/b) without prop-drilling
// through the router. The builder registers its canvas API on mount and clears
// it on unmount; the agent's tools look it up here.
let canvas = null;

export function registerRbdCanvas(api) {
  canvas = api;
  return () => {
    if (canvas === api) canvas = null;
  };
}

export function getRbdCanvas() {
  return canvas;
}

// Wait briefly for the builder to mount/register — used right after navigating
// to the builder so a "build this RBD" request works in one step.
export async function waitForRbdCanvas(timeoutMs = 2500) {
  const start = Date.now();
  while (!canvas && Date.now() - start < timeoutMs) {
    await new Promise((r) => setTimeout(r, 80));
  }
  return canvas;
}
