import SegmentedControl from "./ui/SegmentedControl.jsx";
import { LAYOUTS } from "../tvcData.js";
import "./Tvc.css";

// Covariates that change over time (#60), in the Data step: the switch and
// the layout of the rows (under More options). The item and time columns are
// roles in each column's heading (DataMapper).

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
