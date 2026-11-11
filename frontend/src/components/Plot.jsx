// The chart component, bound to Plotly's *basic* build (scatter, bar and pie
// traces on cartesian axes — every chart the app draws). The default
// ``react-plotly.js`` export bundles the complete, unminified plotly.js
// (~11 MB of source, ~1.5 MB gzipped); the basic build is ~0.3 MB gzipped.
// Using another trace type (heatmap, box, histogram, …) needs a larger build.
//
// Every chart wears the shared theme (src/plotTheme.js): its layout and config
// are merged over the theme's, so a call site sets only what is particular to
// its chart. `download="Bearings — probability plot"` adds small PNG and SVG
// buttons that save the chart named after it (the Plotly toolbar is off).
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import createPlotlyComponent from "react-plotly.js/factory";
import Plotly from "plotly.js-basic-dist-min";
import {
  DATE_LOCALE, DOWNLOAD_ROW, INK, SURFACE, chartFileName, downloadCorner, minPlotSize, ownHeight, reachesCorner, shorterBy,
  themedConfig, themedLayout,
} from "../plotTheme.js";

const PlotlyPlot = createPlotlyComponent(Plotly);

const NARROW = "(max-width: 640px)";
// Where the download buttons always have a row of their own (index.css, .plot-dl).
const ROW_ALWAYS = "(max-width: 640px), (hover: none)";
// Clear space kept between legend text and the buttons.
const CORNER_GAP = 6;

const media = (query) => (typeof window !== "undefined" && window.matchMedia ? window.matchMedia(query) : null);

function useMedia(query) {
  const [matches, setMatches] = useState(() => !!media(query)?.matches);
  useEffect(() => {
    const mq = media(query);
    if (!mq) return undefined;
    const on = () => setMatches(mq.matches);
    on();
    mq.addEventListener?.("change", on);
    return () => mq.removeEventListener?.("change", on);
  }, [query]);
  return matches;
}

// Save the chart as a PNG (2x, for slides) or an SVG (for print and editing):
// on white, at a readable width, titled with its name. `height`: the chart's
// height on screen plus any row it gave up to the buttons, so the image is the
// same wherever the buttons sit.
async function downloadImage(gd, title, format, height = 0) {
  if (!gd) return;
  height = height || gd.offsetHeight || gd.layout?.height || 400;
  const layout = {
    ...gd.layout,
    paper_bgcolor: SURFACE,
    plot_bgcolor: SURFACE,
    title: {
      text: title, x: 0, xref: "paper", xanchor: "left", y: 1, yref: "container", yanchor: "top",
      pad: { t: 16 }, font: { size: 15, color: INK },
    },
    // Room for the title above the legend, which the theme puts above the plot.
    margin: { ...(gd.layout?.margin || {}), t: Math.max(gd.layout?.margin?.t || 0, 80) },
    width: 1000,
    height: height + 48,
  };
  const size = { width: 1000, height: height + 48, scale: format === "png" ? 2 : 1 };
  const url = await Plotly.toImage({ data: gd.data, layout, config: DATE_LOCALE }, { format, ...size });
  const a = document.createElement("a");
  a.href = url;
  a.download = chartFileName(title, format);
  document.body.appendChild(a);
  a.click();
  a.remove();
}

export function DownloadIcon() {
  return (
    <svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true" fill="none" stroke="currentColor"
         strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <path d="M8 2.5v8M4.5 7 8 10.5 11.5 7M3 13.5h10" />
    </svg>
  );
}

// ``fill``: the chart takes its container's height instead of a fixed one
// (the model pages, whose tabs fit the screen). The caller gives the
// container its size (components/model/ModelFrame.css: .plot-fill); the
// chart follows it as it changes, not only when the window does.
export default function Plot({
  layout,
  config,
  download = null,
  style,
  useResizeHandler = true,
  onInitialized,
  onUpdate,
  onAfterPlot,
  fill = false,
  className,
  ...rest
}) {
  const narrow = useMedia(NARROW);
  const rowAlways = useMedia(ROW_ALWAYS);
  const gd = useRef(null);
  const frame = useRef(null);
  const box = useRef(null);
  // The download buttons show over the chart's top right corner on hover and
  // need no room of their own, unless legend text reaches that corner: then
  // they take a slim row above the chart, cut from the chart's own height.
  const [reached, setReached] = useState(false);
  const ownRow = !!download && reached && !rowAlways;
  const measure = useCallback(() => {
    const el = gd.current;
    const dl = frame.current?.querySelector(":scope > .plot-dl");
    if (!el || !dl) return;
    const chart = el.getBoundingClientRect();
    if (!chart.width || !chart.height) return; // not on screen (a closed tab): keep the last answer
    const texts = el.querySelectorAll(".legend .legendtext, .legend .legendtitletext");
    const boxes = Array.from(texts, (t) => t.getBoundingClientRect());
    setReached(reachesCorner(downloadCorner(chart, dl.offsetWidth + CORNER_GAP), boxes));
  }, []);
  // Text is measured again once the page's font has loaded: it sets the widths.
  useEffect(() => {
    if (!download || typeof document === "undefined" || !document.fonts?.ready) return undefined;
    let live = true;
    document.fonts.ready.then(() => { if (live) measure(); }).catch(() => {});
    return () => { live = false; };
  }, [download, measure]);

  const merged = useMemo(() => {
    // A filling chart has no height of its own; one that has gives the
    // buttons' row its height, so the chart is no taller with the row.
    const own = fill ? (layout ? { ...layout, height: undefined } : layout) : ownRow ? shorterBy(layout, DOWNLOAD_ROW) : layout;
    return themedLayout(own, { narrow });
  }, [layout, narrow, fill, ownRow]);
  const cfg = useMemo(() => themedConfig(config), [config]);
  // Never drawn in a box narrower (or, filling, shorter) than its margins plus a
  // plot area: a squeezed box gave Plotly a 2 px plot and axis titles at -Infinity.
  const least = useMemo(() => minPlotSize(merged), [merged]);

  // A filling chart redraws at its box's size when the box changes (a panel
  // beside it loading, the header wrapping, the buttons' row coming or
  // going), which no window event reports.
  useEffect(() => {
    if (!fill || typeof ResizeObserver === "undefined" || !box.current) return undefined;
    let raf = 0;
    const ro = new ResizeObserver(() => {
      cancelAnimationFrame(raf);
      raf = requestAnimationFrame(() => {
        if (gd.current && gd.current.isConnected) Plotly.Plots.resize(gd.current).catch?.(() => {});
      });
    });
    ro.observe(box.current);
    return () => { cancelAnimationFrame(raf); ro.disconnect(); };
  }, [fill]);

  const plot = (
    <PlotlyPlot
      {...rest}
      layout={merged}
      config={cfg}
      // A chart with a height of its own holds it on its box too: Plotly drops
      // the layout's height when the window resizes and reads the box's.
      style={fill
        ? { width: "100%", height: "100%", minWidth: least.width, minHeight: least.height, ...style }
        : { width: "100%", height: ownHeight(layout, ownRow ? DOWNLOAD_ROW : 0), minWidth: least.width, ...style }}
      useResizeHandler={useResizeHandler}
      onInitialized={(fig, div) => { gd.current = div; measure(); onInitialized?.(fig, div); }}
      onUpdate={(fig, div) => { gd.current = div; measure(); onUpdate?.(fig, div); }}
      onAfterPlot={(...args) => { measure(); onAfterPlot?.(...args); }}
    />
  );
  const own = ownRow ? " plot-dl-own" : "";
  // The saved image is as tall as the chart was before it gave up that row.
  const height = () => (gd.current?.offsetHeight || 0) + (ownRow ? DOWNLOAD_ROW : 0);
  if (fill) {
    return (
      <div className={"plot-fill plot-frame" + own + (className ? " " + className : "")} ref={frame}>
        {download && <DownloadButtons title={download} gd={gd} height={height} />}
        <div className="plot-fill-inner" ref={box}>{plot}</div>
      </div>
    );
  }
  if (!download) return plot;
  return (
    <div className={"plot-frame" + own} ref={frame}>
      <DownloadButtons title={download} gd={gd} height={height} />
      {plot}
    </div>
  );
}

function DownloadButtons({ title, gd, height }) {
  return (
    <div className="plot-dl" role="group" aria-label={`Download ${title}`}>
      <DownloadIcon />
      {["png", "svg"].map((format) => (
        <button
          key={format}
          type="button"
          className="plot-dl-btn"
          title={`Download ${format.toUpperCase()}`}
          aria-label={`Download ${title} as ${format.toUpperCase()}`}
          onClick={() => downloadImage(gd.current, title, format, height?.())}
        >
          {format.toUpperCase()}
        </button>
      ))}
    </div>
  );
}
