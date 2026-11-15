import { Link } from "react-router-dom";
import Plot from "./Plot.jsx";
import { ACCENT, bandPair, referenceShape } from "../plotTheme.js";
import { missionCurve, otherDrivers } from "../rbdMission.js";

// The whole mission as one curve (A18): the chance the mission is still going at each point of its
// clock, through every phase, the phase boundaries dashed and named. A simulated mission (blocks on
// standby only a simulation can work out) carries its band: the simulation's own precision, two-sided.
// One component for the Explorer's Missions tab (MissionPane) and the RBD's Calculator
// (RbdPhasesResult).
//
//   result   a mission result ({curve: {t, reliability, lower?, upper?}, phases: [{name, end}], interval?})
//   unit     the diagram's time unit, for the axis      name   the chart's download name
export default function MissionCurve({ result, unit = "", name = "Mission" }) {
  const shape = missionCurve(result);
  if (!shape) return null;
  const { t, r, lower, upper, boundaries } = shape;
  const level = result?.interval?.confidence ? `${Math.round(result.interval.confidence * 100)}% range` : "range";
  const traces = [
    ...(lower ? bandPair(t, lower, upper, { name: `Simulation's ${level}` }) : []),
    {
      type: "scatter",
      mode: "lines",
      x: t,
      y: r,
      name: "Still going",
      line: { color: ACCENT, width: 2 },
      hovertemplate: `%{x:,.4~g}${unit ? ` ${unit}` : ""}: %{y:.4~%} still going<extra></extra>`,
    },
  ];
  return (
    <figure className="mission-curve" aria-label="Reliability through the mission">
      <Plot
        data={traces}
        layout={{
          height: 260,
          showlegend: !!lower,
          margin: { l: 8, r: 16, t: 28, b: 40 },
          xaxis: { title: { text: unit ? `Mission time (${unit})` : "Mission time" }, rangemode: "tozero" },
          yaxis: { title: { text: "Still going" }, tickformat: ".1~%", range: [Math.max(0, Math.min(...r, ...(lower || [])) - 0.02), 1.005] },
          shapes: boundaries.map((b) => referenceShape({ x: b.t })),
          annotations: boundaries.map((b) => ({
            x: b.t, y: 1, xref: "x", yref: "paper", yanchor: "bottom", xanchor: "left", showarrow: false,
            text: b.next, font: { size: 11 },
          })),
        }}
        download={`${name} — reliability through the mission`}
      />
      <figcaption className="rim-tquiet">
        The chance the mission is still going at each point; dashed lines mark where each phase begins.
        {lower ? " The shaded band is the simulation's own precision, not the uncertainty in the blocks' models." : ""}
      </figcaption>
    </figure>
  );
}

// The blocks after the weakest that drive a phase's failures, in words: "Valve (31%), Pump A (12%)";
// "" when there are none. ``row``: a mission result's phase ({drivers: [{label, share}]}).
export function driversText(row) {
  return otherDrivers(row).map((d) => `${d.label} (${Math.round(d.share * 100)}%)`).join(", ");
}

// A mission only a simulation can work out, for someone without Pro (402, code pro_required): the
// server's reason, then what Pro adds and where to get it.
export function MissionProNote({ message }) {
  return (
    <div className="card note mission-pro" role="status">
      <p>{message}</p>
      <p className="rim-tquiet">Pro runs the seeded simulation (20,000 missions), with its range, the curve through the
        mission and what drives each phase&apos;s failures.</p>
      <div className="rbd-upgrade-actions"><Link className="cta cta-solid" to="/billing">Upgrade to Pro</Link></div>
    </div>
  );
}
