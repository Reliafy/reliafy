import { useState } from "react";
import Select from "./Select.jsx";
import Chip from "./ui/Chip.jsx";
// What repairable data can carry beyond its columns' selectors (ColumnMapper:
// i, x, c, n, tl, tr and the failure mode, as "mode"): covariates for
// proportional intensity, and observation gaps — window columns, or windows
// typed in (#65). ``covariates={false}``: the gaps only (the covariates come
// from the dataset's reading).
export default function RecurrentMore({ columns, mapping, onChange, windows = "", onWindowsChange = null, covariates = true }) {
  const setField = (field, value) => onChange({ ...mapping, [field]: value });
  const [typing, setTyping] = useState(!!String(windows || "").trim());
  // Columns free for a covariate: not the system, time or a modifier.
  const used = new Set(["i", "x", "c", "n", "tl", "tr", "mode", "ws", "we"].map((k) => mapping[k]).filter(Boolean));
  const z = mapping.z || [];
  const covariateCols = columns.filter((c) => !used.has(c));
  const toggleZ = (col) => onChange({ ...mapping, z: z.includes(col) ? z.filter((c) => c !== col) : [...z, col] });

  return (
    <div className="mapper ds-mapper">
      <div className="map-group">
        <div className="ds-row rec-map-row">
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
        {covariates && <div className="ds-field rec-map-cov">
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
        </div>}
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
