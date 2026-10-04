import { useState } from "react";
import Modal from "./Modal.jsx";

// Diagram-level costs of a repairable RBD (#99): what an hour (unit) of system
// downtime costs — lost production — and how long the system is owned, for the
// total cost of ownership, and the discount rate (% a year) that makes that
// total a present value (#219). Stored as graph.costs = {downtime_rate,
// horizon, discount_rate}; all optional. Block costs are set on each block.
const isBlank = (v) => v == null || String(v).trim() === "";
// A discount rate is % a year, so the diagram's unit must be a calendar one.
const CALENDAR = /^(s|secs?|seconds?|mins?|minutes?|h|hrs?|hours?|d|days?|wks?|weeks?|mo|mths?|months?|y|yrs?|years?)$/i;

export default function RbdCostsModal({ initial, unit, onClose, onSubmit }) {
  const [rate, setRate] = useState(initial?.downtime_rate ?? "");
  const [horizon, setHorizon] = useState(initial?.horizon ?? "");
  const [discount, setDiscount] = useState(initial?.discount_rate ?? "");
  const u = unit ? unit.replace(/s$/, "") : "time unit";
  const rateOk = isBlank(rate) || (Number.isFinite(Number(rate)) && Number(rate) >= 0);
  const horizonOk = isBlank(horizon) || (Number.isFinite(Number(horizon)) && Number(horizon) > 0);
  const discountOk = isBlank(discount) || (Number.isFinite(Number(discount)) && Number(discount) >= 0 && Number(discount) <= 100);
  const discounted = !isBlank(discount) && Number(discount) > 0;
  const calendarOk = !discounted || CALENDAR.test(String(unit || "").trim());
  const valid = rateOk && horizonOk && discountOk && calendarOk;

  const submit = () => {
    if (!valid) return;
    const costs = {
      ...(isBlank(rate) ? {} : { downtime_rate: Number(rate) }),
      ...(isBlank(horizon) ? {} : { horizon: Number(horizon) }),
      ...(isBlank(discount) || Number(discount) === 0 ? {} : { discount_rate: Number(discount) }),
    };
    onSubmit(Object.keys(costs).length ? costs : null);
  };

  const footer = (
    <>
      <span className="hint">Block costs: double-click a block.</span>
      <div className="row" style={{ margin: 0 }}>
        <button className="secondary" onClick={onClose}>Cancel</button>
        <button onClick={submit} disabled={!valid}>Set costs</button>
      </div>
    </>
  );

  return (
    <Modal title="Diagram costs" onClose={onClose} footer={footer}>
      <p className="muted-line" style={{ marginTop: 0 }}>
        Price the system's downtime to weigh repairs, maintenance and spare units against the
        production they save. Costs are in whatever currency you use; with a discount rate the total
        cost of ownership is a present value.
      </p>
      <div className="param-fields">
        <label className="param-field rbd-cost-field" title="Charged for every unit of time the whole system is down (lost production).">
          <span>System downtime cost</span>
          <input type="number" step="any" min="0" value={rate} placeholder="—" onChange={(e) => setRate(e.target.value)} />
          <small>per {u} the system is down</small>
        </label>
        <label className="param-field rbd-cost-field" title="How long the system is owned: the total cost of ownership is purchase prices + running cost over this long. Blank uses the simulated window.">
          <span>Ownership horizon</span>
          <input type="number" step="any" min="0" value={horizon} placeholder="—" onChange={(e) => setHorizon(e.target.value)} />
          <small>{unit || "time"} · e.g. 87600 h = 10 years</small>
        </label>
        <label className="param-field rbd-cost-field" title="Makes the total cost of ownership a present value: purchases at the start, running costs discounted continuously over the horizon. Converted to the diagram's time unit. Blank or 0: undiscounted.">
          <span>Discount rate</span>
          <input type="number" step="any" min="0" max="100" value={discount} placeholder="—" onChange={(e) => setDiscount(e.target.value)} />
          <small>% a year · e.g. 7</small>
        </label>
      </div>
      {!valid && (
        <ul className="rbd-costs-errors">
          {!rateOk && <li>The downtime cost must be a non-negative number.</li>}
          {!horizonOk && <li>The horizon must be a positive number.</li>}
          {!discountOk && <li>The discount rate must be a percentage a year, from 0 to 100.</li>}
          {discountOk && !calendarOk && (
            <li>A discount rate is a percentage a year, so it needs the diagram in a calendar time unit
              (hours, days, weeks, months or years){unit ? `, not ${unit}` : ""}.</li>
          )}
        </ul>
      )}
    </Modal>
  );
}
