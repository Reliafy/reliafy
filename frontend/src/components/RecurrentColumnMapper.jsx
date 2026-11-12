import { useState } from "react";
import Select from "./Select.jsx";
import Chip from "./ui/Chip.jsx";
// Column mapping for recurrent-event (repairable-system) data, in plain words
// like the life-data ColumnMapper. Required: the system (i) and the time of
// each failure (x). Optional: a censor flag (c), a count (n), the start (tl)
// and end (tr) of each system's record. Then, each optional (#65): the cause
// of each failure, covariates (site, duty, ...) and observation gaps — window
// columns, or windows typed in.
const FIELDS = [
  { key: "i", label: "System or unit", none: "— pick a column —",
    hint: "Which machine each failure belongs to." },
  { key: "x", label: "Time of each failure", none: "— pick a column —",
    hint: "Its age or running time at the failure, counted from new." },
];
const OPTIONAL = [
  { key: "tr", label: "End of record (optional)", none: "— none: each record ends at its last failure —",
    hint: "How far each system's history goes: its age now, or when it left service. Without it the time "
      + "since the last failure is lost and the rate reads too high." },
  { key: "tl", label: "Start of record (optional)", none: "— none: watched from new —",
    hint: "For a system already in service when records began: its age then." },
  { key: "c", label: "Failure or end of record? (optional)", none: "— none: every row is a failure —",
    hint: "A flag column: 0 a failure, 1 the end of the record." },
  { key: "n", label: "Count (optional)", none: "— none: one failure per row —",
    hint: "Failures at that time on that row." },
];

const COMMON_UNITS = [
  "Hours", "Days", "Weeks", "Months", "Years",
  "Cycles", "Kilometres", "Miles", "Operations", "Rounds",
];

const NONE = { value: "", label: "— none —" };

export default function RecurrentColumnMapper({ columns, mapping, onChange, unit, onUnitChange,
                                                windows = "", onWindowsChange = null }) {
  const setField = (field, value) => onChange({ ...mapping, [field]: value });
  const [typing, setTyping] = useState(!!String(windows || "").trim());
  // Columns free for a covariate: not the system, time or a modifier.
  const used = new Set(["i", "x", "c", "n", "tl", "tr", "mode", "ws", "we"].map((k) => mapping[k]).filter(Boolean));
  const z = mapping.z || [];
  const covariateCols = columns.filter((c) => !used.has(c));
  const toggleZ = (col) => onChange({ ...mapping, z: z.includes(col) ? z.filter((c) => c !== col) : [...z, col] });

  const field = (f) => (
    <div className="ds-field" key={f.key}>
      <span className="ds-label" id={`recmap-${f.key}`}>{f.label}</span>
      <Select value={mapping[f.key] || ""} onChange={(v) => setField(f.key, v)} ariaLabel={f.label}
              options={[{ value: "", label: f.none }, ...columns]} />
      {f.hint && <span className="ds-hint">{f.hint}</span>}
    </div>
  );

  return (
    <div className="mapper ds-mapper">
      <div className="ds-row">
        {FIELDS.map(field)}
        {onUnitChange && (
          <label className="ds-field ds-unit">
            <span className="ds-label">Unit</span>
            <input
              className="units-input"
              list="rec-units"
              value={unit || ""}
              placeholder="e.g. Hours"
              onChange={(e) => onUnitChange(e.target.value)}
            />
            <datalist id="rec-units">
              {COMMON_UNITS.map((u) => (
                <option value={u} key={u} />
              ))}
            </datalist>
          </label>
        )}
      </div>
      <div className="ds-row">
        {OPTIONAL.map(field)}
      </div>

      <div className="map-group">
        <div className="map-group-title"><span>Cause, covariates and gaps (optional)</span></div>
        <div className="ds-row rec-map-row">
          <div className="ds-field">
            <span className="ds-label">Cause of each failure</span>
            <Select value={mapping.mode || ""} onChange={(v) => setField("mode", v)} options={[NONE, ...columns]}
                    ariaLabel="Cause of each failure"
                    title="The failure mode or cause: the MCF of each cause, and a growth projection" />
          </div>
          <div className="ds-field">
            <span className="ds-label">Observation windows</span>
            <div className="rec-map-pair">
              <Select value={mapping.ws || ""} onChange={(v) => setField("ws", v)}
                      options={[{ value: "", label: "Start: none" }, ...columns]} title="Each window's start"
                      ariaLabel="Observation window start" />
              <Select value={mapping.we || ""} onChange={(v) => setField("we", v)}
                      options={[{ value: "", label: "End: none" }, ...columns]} title="Each window's end"
                      ariaLabel="Observation window end" />
            </div>
          </div>
        </div>
        <div className="ds-field rec-map-cov">
          <span className="ds-label">Covariates <span className="gof-sub">for proportional intensity</span></span>
          {covariateCols.length > 0 ? (
            <span className="chip-row">
              {covariateCols.map((c) => (
                <Chip key={c} tone={z.includes(c) ? "accent" : "neutral"} onClick={() => toggleZ(c)}
                      aria-pressed={z.includes(c)} title={z.includes(c) ? `Drop ${c}` : `Use ${c} as a covariate`}>
                  {z.includes(c) ? "✓ " : "+ "}{c}
                </Chip>
              ))}
            </span>
          ) : <span className="muted-line" style={{ margin: 0 }}>No other columns.</span>}
        </div>
        {onWindowsChange && (
          typing ? (
            <label className="ds-field rec-map-windows">
              <span className="ds-label">Windows by hand <span className="gof-sub">one a line: system, start, end</span></span>
              <textarea rows={3} value={windows} placeholder={"P-01, 0, 3000\nP-01, 4000, 8760"}
                        onChange={(e) => onWindowsChange(e.target.value)} />
            </label>
          ) : (
            <button type="button" className="link rec-map-link" onClick={() => setTyping(true)}>
              Type in observation windows instead
            </button>
          )
        )}
        <p className="muted-line rec-map-note">
          Windows: when a system wasn't watched for a while (mothballed, records lost), give the periods it was.
          A system without one is watched from its start to its end of observation.
        </p>
      </div>
    </div>
  );
}
