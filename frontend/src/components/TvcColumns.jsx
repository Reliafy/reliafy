import SegmentedControl from "./ui/SegmentedControl.jsx";
import { LAYOUTS } from "../tvcData.js";
import "./Tvc.css";

// Covariates that change over time (#60), in the Data step: the switch and
// the layout of the rows (in the regression section), and the item and time
// columns that take the place of the single time column (in ColumnMapper).

// ``layout``: null (covariates fixed), "intervals" or "timeline".
export function TvcToggle({ layout, onChange }) {
  return (
    <div className="tvc-toggle">
      <label className="cov-adv-toggle">
        <input
          type="checkbox"
          checked={!!layout}
          onChange={(e) => onChange(e.target.checked ? "intervals" : null)}
        />
        Covariates change over time
      </label>
      <span className="ds-hint">
        Each item has several rows, one per stretch at one set of values — a pump whose load steps between
        levels.
      </span>
      {layout && (
        <SegmentedControl
          size="sm"
          label="How the rows are laid out"
          options={LAYOUTS}
          value={layout}
          onChange={onChange}
        />
      )}
    </div>
  );
}

// The item and time fields. ``field(key, label, none, hint)`` and ``unit``
// come from ColumnMapper, so they look and behave like its own.
export function TvcTimeFields({ layout, field, unit }) {
  return (
    <>
      <div className="ds-row">
        {field("i", "Item", "— pick a column —", "The pump, motor or unit each row belongs to.")}
        {unit}
      </div>
      <div className="ds-row">
        {layout === "intervals" ? (
          <>
            {field("xl", "Start of the row", "— pick a column —", "When this stretch of the item's life began.")}
            {field("xr", "End of the row", "— pick a column —", "When it ended: a failure, a change, or the end of records.")}
          </>
        ) : (
          field("x", "Time of the row", "— pick a column —",
                "When the row's values take effect. An item's last row is when it failed or was removed.")
        )}
      </div>
    </>
  );
}

// What the status column says, per layout.
export const TVC_STATUS = {
  intervals: "Did the row end in a failure?",
  timeline: "Failed or still running (at the item's last row)?",
};
