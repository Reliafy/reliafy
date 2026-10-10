import { useState } from "react";
import Select from "./Select.jsx";
import Chip from "./ui/Chip.jsx";
// Column-mapping UI for recurrent-event (repairable-system) data — the same
// grouped look as the life-data ColumnMapper. Required: i (system id) and x
// (event time). Optional modifiers mirror SurPyval's surface: c/n/tl/tr, where
// tr is each system's observation window (right truncation). Then, each
// optional (#65): the cause of each failure, covariates (site, duty, ...) and
// observation gaps — window columns, or windows typed in.
const FIELD_INFO = {
  i: { label: "i", help: "System / unit id — groups events by machine", req: true },
  x: { label: "x", help: "Event time (failure / repair)", req: true },
  c: { label: "c", help: "Censor flag: 0 event, 1 right, -1 left" },
  n: { label: "n", help: "Count of events per row" },
  tl: { label: "tl", help: "Left truncation — observation start / left entry" },
  tr: { label: "tr", help: "Right truncation — each system's observation window" },
};

const COMMON_UNITS = [
  "Hours", "Days", "Weeks", "Months", "Years",
  "Cycles", "Kilometres", "Miles", "Operations", "Rounds",
];

const GROUPS = [
  { title: "Event — system and time", fields: ["i", "x"], cols: 2 },
  { title: "Modifiers (optional)", fields: ["c", "n", "tl", "tr"], cols: 4 },
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

  return (
    <div className="mapper">
      {GROUPS.map((group) => {
        // The unit of the time axis sits inline with the required i/x row.
        const withUnit = group.fields.includes("x") && !!onUnitChange;
        return (
          <div className="map-group" key={group.title}>
            <div className="map-group-title">
              <span>{group.title}</span>
            </div>
            <div className="map-fields" data-cols={withUnit ? group.cols + 1 : group.cols}>
              {group.fields.map((field) => {
                const info = FIELD_INFO[field];
                const selected = !!mapping[field];
                return (
                  <label
                    className={"map-field" + (selected ? " selected" : "")}
                    key={field}
                    htmlFor={`recmap-${field}`}
                    title={`${info.label}${info.req ? " (required)" : ""} — ${info.help}`}
                  >
                    <span className="map-badge">
                      {info.label}
                      {info.req && <i className="req">*</i>}
                    </span>
                    <Select
                      className="sel-embedded"
                      value={mapping[field] || ""}
                      onChange={(v) => setField(field, v)}
                      options={[NONE, ...columns]}
                    />
                  </label>
                );
              })}
              {withUnit && (
                <label className="map-field map-unit" title="Unit of the time axis (optional)">
                  <span className="map-badge">unit</span>
                  <input
                    className="map-unit-input"
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
          </div>
        );
      })}

      <div className="map-group">
        <div className="map-group-title"><span>Cause, covariates and gaps (optional)</span></div>
        <div className="ds-row rec-map-row">
          <div className="ds-field">
            <span className="ds-label">Cause of each failure</span>
            <Select value={mapping.mode || ""} onChange={(v) => setField("mode", v)} options={[NONE, ...columns]}
                    title="The failure mode or cause: the MCF of each cause, and a growth projection" />
          </div>
          <div className="ds-field">
            <span className="ds-label">Observation windows</span>
            <div className="rec-map-pair">
              <Select value={mapping.ws || ""} onChange={(v) => setField("ws", v)}
                      options={[{ value: "", label: "Start: none" }, ...columns]} title="Each window's start" />
              <Select value={mapping.we || ""} onChange={(v) => setField("we", v)}
                      options={[{ value: "", label: "End: none" }, ...columns]} title="Each window's end" />
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
