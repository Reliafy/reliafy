// The chart component, bound to Plotly's *basic* build (scatter, bar and pie
// traces on cartesian axes — every chart the app draws). The default
// ``react-plotly.js`` export bundles the complete, unminified plotly.js
// (~11 MB of source, ~1.5 MB gzipped); the basic build is ~0.3 MB gzipped.
// Using another trace type (heatmap, box, histogram, …) needs a larger build.
//
// Every chart wears the shared theme (src/plotTheme.js): its layout and config
// are merged over the theme's, so a call site sets only what is particular to
// its chart. `download="Bearings — probability plot"` adds a small button that
// saves the chart as a PNG named after it (the Plotly toolbar is off).
import { useEffect, useMemo, useRef, useState } from "react";
import createPlotlyComponent from "react-plotly.js/factory";
import Plotly from "plotly.js-basic-dist-min";
import { INK, SURFACE, slugify, themedConfig, themedLayout } from "../plotTheme.js";

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

// Save the chart as a PNG: on white, at a readable width, titled with its name.
async function downloadPng(gd, title) {
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
  const url = await Plotly.toImage({ data: gd.data, layout }, { format: "png", width: 1000, height: height + 48, scale: 2 });
  const a = document.createElement("a");
  a.href = url;
  a.download = `${slugify(title)}.png`;
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

export default function Plot({
  layout,
  config,
  download = null,
  style,
  useResizeHandler = true,
  onInitialized,
  onUpdate,
  ...rest
}) {
  const narrow = useNarrow();
  const gd = useRef(null);
  const merged = useMemo(() => {
    const l = themedLayout(layout, { narrow });
    // Room at the top right for the download button when nothing else (a
    // legend) pushes the margin there.
    return download ? { ...l, margin: { ...l.margin, t: Math.max(l.margin?.t ?? 0, 32) } } : l;
  }, [layout, narrow, download]);
  const cfg = useMemo(() => themedConfig(config), [config]);

  const plot = (
    <PlotlyPlot
      {...rest}
      layout={merged}
      config={cfg}
      style={{ width: "100%", ...style }}
      useResizeHandler={useResizeHandler}
      onInitialized={(fig, div) => { gd.current = div; onInitialized?.(fig, div); }}
      onUpdate={(fig, div) => { gd.current = div; onUpdate?.(fig, div); }}
    />
  );
  if (!download) return plot;
  return (
    <div className="plot-frame">
      <button
        type="button"
        className="plot-dl"
        title="Download PNG"
        aria-label={`Download ${download} as PNG`}
        onClick={() => downloadPng(gd.current, download)}
      >
        <DownloadIcon />
      </button>
      {plot}
    </div>
  );
}
