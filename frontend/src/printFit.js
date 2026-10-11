// Printing a share page (#30). Charts and block diagrams are drawn at the
// screen's width, and paper is narrower: Plotly doesn't redraw for print and
// a diagram keeps its screen zoom, so on A4 or Letter they'd be clipped.
//
// Just before printing, `html.print-layout` switches the page to the printed
// column's width (A4's, the narrower of the two; see views/PublicPage.css). Each
// chart and diagram is then scaled down (CSS zoom) to the width its box has
// in that layout, and put back after printing. Zoom scales the drawing and
// its box together, so nothing is clipped and nothing overlaps.

export const FIT_SELECTOR = ".js-plotly-plot, .public-rbd-canvas";
const LAYOUT_CLASS = "print-layout";

// The scale that fits a drawing `width` px wide into `room` px: never above 1.
export function printZoom(width, room) {
  if (!(width > 0) || !(room > 0) || room >= width) return 1;
  return Math.floor((room / width) * 1000) / 1000;
}

function contentWidth(el) {
  if (!el) return 0;
  const style = getComputedStyle(el);
  return el.clientWidth - parseFloat(style.paddingLeft || 0) - parseFloat(style.paddingRight || 0);
}

function fit(root) {
  const els = [...root.querySelectorAll(FIT_SELECTOR)];
  // Measure every drawing at its screen size, then the room it has once the
  // print layout applies.
  const before = els.map((el) => ({ el, width: el.offsetWidth, height: el.offsetHeight }));
  document.documentElement.classList.add(LAYOUT_CLASS);
  for (const { el, width, height } of before) {
    const room = contentWidth(el.parentElement) || width;
    const zoom = printZoom(width, room);
    el.dataset.printFit = "1";
    // Keep the screen size, so the drawing itself isn't redrawn, and scale it.
    el.style.width = `${width}px`;
    if (el.classList.contains("public-rbd-canvas")) el.style.height = `${height}px`;
    el.style.zoom = String(zoom);
  }
}

function unfit(root) {
  document.documentElement.classList.remove(LAYOUT_CLASS);
  for (const el of root.querySelectorAll("[data-print-fit]")) {
    el.style.zoom = "";
    el.style.width = "";
    el.style.height = "";
    delete el.dataset.printFit;
  }
}

// Fit the page under `root` (a selector) for printing while the browser
// prints it. Returns the cleanup for useEffect.
export function installPrintFit(selector) {
  if (typeof window === "undefined") return () => {};
  let fitted = false;
  const root = () => document.querySelector(selector) || document.body;
  const before = () => {
    if (fitted) return;
    fitted = true;
    fit(root());
  };
  const after = () => {
    if (!fitted) return;
    fitted = false;
    unfit(root());
  };
  // beforeprint/afterprint where supported; the print media query as well,
  // for browsers (and headless PDF renderers) that only switch the media.
  const mq = window.matchMedia ? window.matchMedia("print") : null;
  const onMedia = (e) => (e.matches ? before() : after());
  window.addEventListener("beforeprint", before);
  window.addEventListener("afterprint", after);
  mq?.addEventListener?.("change", onMedia);
  return () => {
    window.removeEventListener("beforeprint", before);
    window.removeEventListener("afterprint", after);
    mq?.removeEventListener?.("change", onMedia);
    after();
  };
}
