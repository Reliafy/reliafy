import { useEffect, useState } from "react";
import SegmentedControl from "./ui/SegmentedControl.jsx";
import "./RbdProduction.css";
import { capacityFromRows, capacityRows, capacitySummary } from "../rbdCapacity.js";

// A block's capacity (#122), its own folded section of the block dialog: the
// throughput while it works — one value, or levels it works at with the share
// of its up time at each (a multi-state block). Used by the production
// availability on the Calculator tab; a block left empty limits nothing.
//
// ``onChange({ value, valid })``: ``value`` is null (no capacity), a number,
// or ``[{ value, probability }]`` (probabilities adding up to 1).
export default function RbdCapacityFold({ initial, onChange }) {
  const start = capacityRows(initial);
  const [mode, setMode] = useState(start.length > 1 ? "levels" : "one");
  const [rows, setRows] = useState(start.length ? start : [{ value: "", share: "100" }]);
  const [open, setOpen] = useState(initial != null);

  const parsed = capacityFromRows(mode === "one" ? rows.slice(0, 1).map((r) => ({ ...r, share: "100" })) : rows);
  useEffect(() => {
    onChange?.(parsed);
  }, [JSON.stringify(parsed)]); // eslint-disable-line react-hooks/exhaustive-deps

  const set = (i, patch) => setRows((rs) => rs.map((r, j) => (j === i ? { ...r, ...patch } : r)));
  const switchMode = (m) => {
    setMode(m);
    if (m === "levels" && rows.length < 2) setRows([{ ...rows[0], share: rows[0].share || "80" }, { value: "", share: "" }]);
  };

  return (
    <details className="rbd-dlg-fold" open={open} onToggle={(e) => setOpen(e.currentTarget.open)}>
      <summary>
        Capacity <span className="muted"> · {capacitySummary(parsed.valid ? parsed.value : null)}</span>
      </summary>
      <div className="rbd-dlg-fold-body rbd-capacity">
        <p className="hint">
          What it delivers while it works, for the production availability. Blocks in series pass the least of
          their capacities; blocks in parallel add up. Leave it empty for a block that limits nothing.
        </p>
        <SegmentedControl
          label="Capacity"
          size="sm"
          value={mode}
          onChange={switchMode}
          options={[
            { value: "one", label: "One value" },
            { value: "levels", label: "Levels", title: "A block that works at reduced output part of the time" },
          ]}
        />
        {mode === "one" ? (
          <label className="param-field rbd-capacity-one">
            <span>Capacity while it works</span>
            <input
              type="number" min="0" step="any" placeholder="none" aria-label="Capacity while it works"
              value={rows[0].value} onChange={(e) => set(0, { value: e.target.value })}
            />
          </label>
        ) : (
          <div className="rbd-capacity-levels">
            <div className="rbd-capacity-head" aria-hidden="true">
              <span>Capacity</span>
              <span>Share of up time (%)</span>
            </div>
            {rows.map((r, i) => (
              <div className="rbd-capacity-row" key={i}>
                <input
                  type="number" min="0" step="any" aria-label={`Level ${i + 1} capacity`}
                  value={r.value} onChange={(e) => set(i, { value: e.target.value })}
                />
                <input
                  type="number" min="0" max="100" step="any" aria-label={`Level ${i + 1} share of up time (%)`}
                  value={r.share} onChange={(e) => set(i, { share: e.target.value })}
                />
                <button
                  type="button" className="ghost sm" aria-label={`Remove level ${i + 1}`}
                  disabled={rows.length <= 2} onClick={() => setRows((rs) => rs.filter((_, j) => j !== i))}
                >
                  ×
                </button>
              </div>
            ))}
            <button
              type="button" className="link" disabled={rows.length >= 10}
              onClick={() => setRows((rs) => [...rs, { value: "", share: "" }])}
            >
              + Add a level
            </button>
          </div>
        )}
        {!parsed.valid && <p className="rbd-capacity-error" role="alert">{parsed.error}</p>}
      </div>
    </details>
  );
}
