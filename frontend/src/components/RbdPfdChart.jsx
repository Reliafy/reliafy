import Plot from "./Plot.jsx";
import { DANGER, MUTED, fitLine, referenceShape } from "../plotTheme.js";
import { unitInText } from "./unitText.js";
import { bandsIn, pfdRange, silLimit } from "../rbdOwnership.js";

// A safety function's PFD(t) (#322): RePyability's own point unavailability
// (``exact.curve.unavailability``), which keeps the digits 1 − A(t) loses near
// 1, on a log axis with the low-demand SIL bands behind it, the PFDavg dashed
// (its value is the answer card's) and the target band's limit dotted. A
// result saved before #322 has only A(t): its PFD(t) is 1 − A(t) there.

const BAND_FILLS = ["rgba(20, 23, 28, 0.035)", "rgba(20, 23, 28, 0.07)"];

export default function RbdPfdChart({ exact, safety, unit }) {
  const c = exact?.curve || {};
  if (!(c.t?.length > 1)) return null;
  const fromLibrary = Array.isArray(c.unavailability) && c.unavailability.length === c.t.length;
  const raw = fromLibrary ? c.unavailability : c.availability.map((a) => (a == null ? null : 1 - a));
  // A log axis has no 0: the first instant (every block new) drops out.
  const pfd = raw.map((v) => (v != null && v > 0 ? v : null));
  const limit = safety.target_sil ?? safety.sil;
  const range = pfdRange(pfd, safety.pfd_avg, limit);
  if (!range) return null;
  const u = unit ? ` ${unitInText(unit)}` : "";
  const xTitle = unit ? `Time ${exact.from === "now" ? "from now" : "from new"} (${unit})` : "Time";
  // The SIL bands inside the axis, alternately shaded, labelled in the right
  // margin (clear of the curve).
  const bands = bandsIn(range);
  const shapes = [
    ...bands.map((n) => ({
      type: "rect", xref: "paper", x0: 0, x1: 1, y0: 10 ** -(n + 1), y1: 10 ** -n,
      fillcolor: BAND_FILLS[n % 2], line: { width: 0 }, layer: "below",
    })),
    ...(safety.pfd_avg != null ? [referenceShape({ y: safety.pfd_avg })] : []),
    ...(limit ? [referenceShape({ y: silLimit(limit), line: { color: DANGER, dash: "dot", width: 1 } })] : []),
  ];
  // Annotations on a log axis take the log of the value.
  const annotations = [
    ...bands.map((n) => ({
      xref: "paper", x: 1, xanchor: "left", xshift: 6, y: -(n + 0.5), yanchor: "middle", showarrow: false,
      text: `SIL ${n}`, font: { size: 12, color: MUTED },
    })),
    ...(limit ? [{
      xref: "paper", x: 1, xanchor: "right", y: Math.log10(silLimit(limit)), yanchor: "bottom", showarrow: false,
      text: `SIL ${limit} limit`, font: { size: 12, color: DANGER },
    }] : []),
  ];
  return (
    <Plot
      download="PFD over time"
      data={[fitLine({
        x: c.t, y: pfd, name: "PFD(t)", connectgaps: false,
        hovertemplate: `t = %{x:,.4~g}${u}<br>PFD(t) = %{y:.3~e}<extra></extra>`,
      })]}
      layout={{
        height: 300,
        xaxis: { title: { text: xTitle } },
        yaxis: { title: { text: "PFD(t)" }, type: "log", range, dtick: 1, exponentformat: "power" },
        shapes,
        annotations,
        margin: { r: 48 },
        showlegend: false,
      }}
    />
  );
}
