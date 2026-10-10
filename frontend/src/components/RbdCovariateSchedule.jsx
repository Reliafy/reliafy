import { useId, useRef, useState } from "react";
import Select from "./Select.jsx";
import { withUnit } from "./stressName.js";
import { formatNumber } from "../format.js";
import { unitInText } from "./unitText.js";
import { PRESETS, presetExpression, stairPoints, stairValueAt } from "../rbdTvc.js";

// One covariate's schedule in the node covariate modal (#52): an expression
// in t with presets that insert an editable template (numeric covariates),
// or a phase table that can repeat (categorical ones).
export default function RbdCovariateSchedule({ field, draft, onDraft, unit, tMax, value }) {
  const id = useId();
  if (field.type !== "number") {
    return <PhaseTable field={field} draft={draft} onDraft={onDraft} unit={unit} />;
  }
  const insert = (preset) =>
    onDraft({ expression: presetExpression(preset, field, { value, tMax, unit }) });
  return (
    <div className="rbd-sched">
      <div className="rbd-sched-presets" role="group" aria-label={`Presets for ${field.name}`}>
        {PRESETS.map((p) => (
          <button key={p.id} type="button" className="chip chip-neutral chip-btn" title={p.title} onClick={() => insert(p.id)}>
            {p.label}
          </button>
        ))}
      </div>
      <label className="rbd-sched-expr" htmlFor={id}>
        <span className="sr-only">{withUnit(field.name, field.unit)} as an expression in t</span>
        <input
          id={id}
          type="text"
          spellCheck={false}
          autoComplete="off"
          maxLength={400}
          value={draft?.expression ?? ""}
          placeholder="60 if t < 1000 else 90"
          onChange={(e) => onDraft({ expression: e.target.value })}
        />
      </label>
      <p className="hint rbd-sched-hint">
        In t ({unitWord(unit)}), changing in steps: floor(t / 500), t % 24 &lt; 8, or a comparison.
      </p>
    </div>
  );
}

function unitWord(unit) {
  return unitInText(unit) || "time";
}

// A categorical covariate's phases: the level from each time on, optionally
// repeating every period.
function PhaseTable({ field, draft, onDraft, unit }) {
  const rows = draft?.table || [];
  const options = field.options || [];
  const set = (i, patch) => onDraft({ ...draft, table: rows.map((r, j) => (j === i ? { ...r, ...patch } : r)) });
  const add = () => {
    const last = rows[rows.length - 1];
    const next = last && last.t !== "" ? String(Number(last.t) * 2 || 100) : "";
    onDraft({ ...draft, table: [...rows, { t: next, value: options[0] ?? "" }] });
  };
  const remove = (i) => onDraft({ ...draft, table: rows.filter((_, j) => j !== i) });
  return (
    <div className="rbd-sched">
      <table className="rbd-sched-table">
        <thead>
          <tr>
            <th scope="col">From t ({unitWord(unit)})</th>
            <th scope="col">{field.name}</th>
            <th scope="col"><span className="sr-only">Remove</span></th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i}>
              <td>
                <input
                  type="number"
                  min="0"
                  step="any"
                  aria-label={`Phase ${i + 1} starts at`}
                  value={r.t}
                  disabled={i === 0}
                  onChange={(e) => set(i, { t: e.target.value })}
                />
              </td>
              <td>
                <Select value={r.value} onChange={(v) => set(i, { value: v })} options={options} />
              </td>
              <td>
                {i > 0 && (
                  <button type="button" className="ghost sm" aria-label={`Remove phase ${i + 1}`} onClick={() => remove(i)}>
                    ×
                  </button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="rbd-sched-table-foot">
        <button type="button" className="link" onClick={add}>
          Add phase
        </button>
        <label className="rbd-sched-period">
          <span>Repeat every ({unitWord(unit)})</span>
          <input
            type="number"
            min="0"
            step="any"
            placeholder="No repeat"
            value={draft?.period ?? ""}
            onChange={(e) => onDraft({ ...draft, period: e.target.value })}
          />
        </label>
      </div>
    </div>
  );
}

// The block's preview: each scheduled covariate's stair-step path Z(t) and
// the block's reliability R(t) along it.
export function RbdSchedulePreview({ preview, error, loading, unit }) {
  if (error) {
    return (
      <p className="rbd-sched-error" role="alert">
        {error}
      </p>
    );
  }
  if (!preview) {
    return <p className="hint rbd-sched-loading">{loading ? "Working out the preview…" : ""}</p>;
  }
  const xMax = preview.x[preview.x.length - 1];
  // A repeating path is drawn over its first three cycles: any more is a solid block.
  const zMax = preview.repeats_every ? Math.min(xMax, 3 * preview.repeats_every) : xMax;
  const scheduled = preview.covariates.filter((c) => c.scheduled);
  return (
    <div className={"rbd-sched-preview" + (loading ? " is-loading" : "")} aria-busy={loading || undefined}>
      <div className="rbd-sched-sparks">
        {scheduled.map((c) => (
          <Spark
            key={c.name}
            title={withUnit(c.name, c.unit)}
            unit={unit}
            xMax={zMax}
            stair={{ times: c.times, values: c.values }}
            categories={c.type === "category" ? [...new Set(c.values)] : null}
            range={c.range}
            valueUnit={c.unit}
          />
        ))}
        <Spark
          title="Block reliability R(t)"
          unit={unit}
          xMax={xMax}
          line={{ x: preview.x, y: preview.sf }}
          yDomain={[0, 1]}
          percent
        />
      </div>
      {preview.repeats_every ? (
        <p className="hint rbd-sched-note">Repeats every {formatNumber(preview.repeats_every)} {unitWord(unit)}.</p>
      ) : null}
      {preview.warnings?.map((w) => (
        <p key={w} className="rbd-sched-warn">
          {w}
        </p>
      ))}
    </div>
  );
}

const W = 240;
const H = 72;
const PAD = { l: 4, r: 4, t: 6, b: 6 };

// A small chart: a stair-step covariate path or the reliability line, with a
// crosshair and its value on hover. One series, so no legend: the title names it.
function Spark({ title, unit, xMax, stair, line, categories, range, yDomain, percent, valueUnit }) {
  const [hover, setHover] = useState(null);
  const svgRef = useRef(null);
  let lo;
  let hi;
  let shownLo;
  let shownHi;
  const index = categories ? new Map(categories.map((c, i) => [c, i])) : null;
  const yOf = (v) => (index ? index.get(v) ?? 0 : Number(v));
  if (yDomain) [lo, hi] = yDomain;
  else if (index) [lo, hi] = [-0.5, Math.max(categories.length - 0.5, 0.5)];
  else {
    const vals = stair.values.map(Number).filter(Number.isFinite);
    lo = Math.min(...vals, ...(range ? [range[0]] : []));
    hi = Math.max(...vals, ...(range ? [range[1]] : []));
    if (!(hi > lo)) [lo, hi] = [lo - 1, hi + 1];
    [shownLo, shownHi] = [lo, hi];
    const pad = (hi - lo) * 0.08;
    lo -= pad;
    hi += pad;
  }
  const sx = (x) => PAD.l + (x / (xMax || 1)) * (W - PAD.l - PAD.r);
  const sy = (v) => H - PAD.b - ((yOf(v) - lo) / (hi - lo)) * (H - PAD.t - PAD.b);
  const pts = stair
    ? stairPoints(stair.times, stair.values, xMax)
    : line.x.map((x, i) => [x, line.y[i]]).filter(([, y]) => y != null);
  const d = pts.map(([x, y], i) => `${i ? "L" : "M"}${sx(x).toFixed(1)},${sy(y).toFixed(1)}`).join("");
  const fmtY = (v) =>
    percent ? `${formatNumber(v * 100, { sig: 3 })}%` : index ? String(v) : `${formatNumber(v)}${valueUnit === "%" ? "%" : valueUnit ? ` ${valueUnit}` : ""}`;
  const at = (x) => {
    if (stair) return stairValueAt(stair.times, stair.values, x);
    let best = 0;
    for (let i = 0; i < line.x.length; i++) if (Math.abs(line.x[i] - x) < Math.abs(line.x[best] - x)) best = i;
    return line.y[best];
  };
  const onMove = (e) => {
    const box = svgRef.current?.getBoundingClientRect();
    if (!box) return;
    const frac = (e.clientX - box.left) / box.width;
    const x = Math.min(Math.max(((frac * W - PAD.l) / (W - PAD.l - PAD.r)) * xMax, 0), xMax);
    setHover({ x, y: at(x) });
  };
  const rangeBand =
    range && !index && !yDomain ? (
      <rect
        x={PAD.l}
        width={W - PAD.l - PAD.r}
        y={sy(range[1])}
        height={Math.max(sy(range[0]) - sy(range[1]), 0)}
        className="rbd-spark-range"
      />
    ) : null;
  return (
    <figure className="rbd-spark">
      <figcaption>
        <span>{title}</span>
        <span className="rbd-spark-read">
          {hover
            ? `${fmtY(hover.y)} at t = ${formatNumber(hover.x)}`
            : index
              ? categories.join(" · ")
              : `${fmtY(yDomain ? lo : shownLo)} to ${fmtY(yDomain ? hi : shownHi)}`}
        </span>
      </figcaption>
      <svg
        ref={svgRef}
        viewBox={`0 0 ${W} ${H}`}
        preserveAspectRatio="none"
        role="img"
        aria-label={`${title} from 0 to ${formatNumber(xMax)} ${unitWord(unit)}`}
        onMouseMove={onMove}
        onMouseLeave={() => setHover(null)}
      >
        {rangeBand}
        <path d={d} className="rbd-spark-line" vectorEffect="non-scaling-stroke" />
        {hover && (
          <line x1={sx(hover.x)} x2={sx(hover.x)} y1={PAD.t} y2={H - PAD.b} className="rbd-spark-cross" vectorEffect="non-scaling-stroke" />
        )}
      </svg>
      <div className="rbd-spark-axis" aria-hidden="true">
        <span>0</span>
        <span>
          {formatNumber(xMax)} {unitWord(unit)}
        </span>
      </div>
    </figure>
  );
}
