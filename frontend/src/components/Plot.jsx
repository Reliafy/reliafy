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
import { useEffect, useMemo, useRef, useState } from "react";
import createPlotlyComponent from "react-plotly.js/factory";
import Plotly from "plotly.js-basic-dist-min";
import { INK, SURFACE, chartFileName, themedConfig, themedLayout } from "../plotTheme.js";

const PlotlyPlot = createPlotlyComponent(Plotly);

const NARROW = "(max-width: 640px)";

const media = () => (typeof window !== "undefined" && window.matchMedia ? window.matchMedia(NARROW) : null);

function useNarrow() {
  const [narrow, setNarrow] = useState(() => !!media()?.matches);
  useEffect(() => {
    const mq = media();
    if (!mq) return undefined;
    const on = () => setNarrow(mq.matches);
    mq.addEventListener?.("change", on);
    return () => mq.removeEventListener?.("change", on);
  }, []);
  return narrow;
}

// Save the chart as a PNG (2x, for slides) or an SVG (for print and editing):
// on white, at a readable width, titled with its name.
async function downloadImage(gd, title, format) {
  if (!gd) return;
  const height = gd.offsetHeight || gd.layout?.height || 400;
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
  const url = await Plotly.toImage({ data: gd.data, layout }, { format, ...size });
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
  fill = false,
  className,
  ...rest
}) {
  const narrow = useNarrow();
  const gd = useRef(null);
  const box = useRef(null);
  const merged = useMemo(() => {
    // The download button shows over the chart on hover, so it needs no room
    // of its own. A filling chart has no height of its own.
    const own = fill && layout ? { ...layout, height: undefined } : layout;
    return themedLayout(own, { narrow });
  }, [layout, narrow, fill]);
  const cfg = useMemo(() => themedConfig(config), [config]);

  // A filling chart redraws at its box's size when the box changes (a panel
  // beside it loading, the header wrapping), which no window event reports.
  useEffect(() => {
    if (!fill || typeof ResizeObserver === "undefined" || !box.current) return undefined;
    let frame = 0;
    const ro = new ResizeObserver(() => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        if (gd.current && gd.current.isConnected) Plotly.Plots.resize(gd.current).catch?.(() => {});
      });
    });
    ro.observe(box.current);
    return () => { cancelAnimationFrame(frame); ro.disconnect(); };
  }, [fill]);

  const plot = (
    <PlotlyPlot
      {...rest}
      layout={merged}
      config={cfg}
      style={fill ? { width: "100%", height: "100%", ...style } : { width: "100%", ...style }}
      useResizeHandler={useResizeHandler}
      onInitialized={(fig, div) => { gd.current = div; onInitialized?.(fig, div); }}
      onUpdate={(fig, div) => { gd.current = div; onUpdate?.(fig, div); }}
    />
  );
  if (fill) {
    return (
      <div className={"plot-fill plot-frame" + (className ? " " + className : "")} ref={box}>
        {download && <DownloadButtons title={download} gd={gd} />}
        <div className="plot-fill-inner">{plot}</div>
      </div>
    );
  }
  if (!download) return plot;
  return (
    <div className="plot-frame">
      <DownloadButtons title={download} gd={gd} />
      {plot}
    </div>
  );
}

function DownloadButtons({ title, gd }) {
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
          onClick={() => downloadImage(gd.current, title, format)}
        >
          {format.toUpperCase()}
        </button>
      ))}
    </div>
  );
}
