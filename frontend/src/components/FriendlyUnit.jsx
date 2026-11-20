import { useSyncExternalStore } from "react";
import SegmentedControl from "./ui/SegmentedControl.jsx";
import { FRIENDLY_CONVENTION, FRIENDLY_UNITS, calendarUnit, loadFriendlyUnit, pickFriendlyUnit,
         saveFriendlyUnit } from "../friendlyTime.js";

// The viewer's friendly time unit (friendlyTime.js), shared by every answer on
// the page so one switch moves them all, and remembered per browser.
let chosen;
const listeners = new Set();
const read = () => {
  if (chosen === undefined) chosen = loadFriendlyUnit();
  return chosen;
};
const subscribe = (fn) => {
  listeners.add(fn);
  return () => listeners.delete(fn);
};
function choose(unit) {
  chosen = calendarUnit(unit);
  saveFriendlyUnit(chosen);
  listeners.forEach((fn) => fn());
}

// The friendly unit to show for a model in ``unit`` whose headline answer is
// ``headline`` (in the model's unit): null when the unit isn't calendar time.
export function useFriendlyUnit(unit, headline) {
  const mine = useSyncExternalStore(subscribe, read, () => null);
  return pickFriendlyUnit(mine, headline, unit);
}

const LABEL = { hours: "Hours", days: "Days", weeks: "Weeks", months: "Months", years: "Years" };

// The switch beside the answers: "Also in" one of hours … years (the model's
// own unit shows nothing extra), with the conversion's convention once.
// Nothing renders when the model's unit isn't calendar time.
export default function FriendlyUnitSwitch({ unit, value, className }) {
  if (!calendarUnit(unit) || !value) return null;
  return (
    <div className={"friendly-unit-switch" + (className ? " " + className : "")}>
      <span className="friendly-unit-label">Also in</span>
      <SegmentedControl
        size="sm"
        label="Also show the answers in"
        value={value}
        onChange={choose}
        options={FRIENDLY_UNITS.map((u) => ({
          value: u, label: LABEL[u],
          title: u === calendarUnit(unit) ? "The model's own unit: nothing extra" : undefined,
        }))}
      />
      <span className="friendly-unit-note">{FRIENDLY_CONVENTION}</span>
    </div>
  );
}
