// A fleet forecast's maintenance strategy (Forecasts): run to failure, or
// replace each item at an age, with the prices of a failure and of a planned
// replacement. The fields sit in the forecast's settings; the answer card
// shows failures, planned replacements, parts and cost, by year, with their
// 90% ranges, from the forecast's own simulation (backend/services/fleet_strategy.py).
import Select from "./Select.jsx";
import { CardHeader } from "./ui/Card.jsx";
import ResultSummary from "./ui/ResultSummary.jsx";
import ScrollCue from "./ui/ScrollCue.jsx";
import { formatNumber, formatWithUnit } from "../format.js";
import { costLabel, formatCost, workspaceCurrency } from "../money.js";
import { unitInText } from "./unitText.js";
import { rangeLevelText } from "../levels.js";
import { firstPeriodsParts, rangeText } from "../fleetStrategy.js";

const blank = (v) => v === null || v === undefined || v === "";

const OPTIONS = [
  { value: "run_to_failure", label: "Run to failure", hint: "Each item is replaced when it fails." },
  { value: "age", label: "Replace at an age", hint: "Each item is also replaced when it reaches an age, failed or not." },
];

// The strategy fields, in the forecast's settings form.
export function FleetStrategyFields({ settings, unit, readOnly, onSetting }) {
  const kind = settings.strategy || "run_to_failure";
  const u = unit ? ` (${unit})` : "";
  const field = (key, text, extra = {}) => (
    <label className="login-field" style={{ width: 170 }}>
      <span>{text}</span>
      {readOnly ? <span>{blank(settings[key]) ? "—" : formatNumber(settings[key], { sig: 6 })}</span> : (
        <input type="number" inputMode="decimal" min="0" step="any" value={settings[key] ?? ""}
               onChange={(e) => onSetting(key, e.target.value === "" ? null : e.target.value)} {...extra} />
      )}
    </label>
  );
  return (
    <>
      <h3 className="fleet-assume-h">Maintenance strategy</h3>
      <div className="row" style={{ gap: "0.8rem", alignItems: "flex-end", flexWrap: "wrap", marginTop: 0 }}>
        <label className="login-field" style={{ minWidth: 200 }}>
          <span>Strategy</span>
          <Select value={kind} onChange={(v) => onSetting("strategy", v)} options={OPTIONS} disabled={readOnly} />
        </label>
        {kind === "age" && field("replace_at", `Replace at age${u}`, { placeholder: "required" })}
        {field("failure_cost", costLabel("Cost of a failure", workspaceCurrency()), { placeholder: "optional" })}
        {kind === "age" && field("planned_cost", costLabel("Cost of a planned replacement", workspaceCurrency()),
                                 { placeholder: "optional" })}
      </div>
      <p className="muted-line" style={{ marginBottom: 0 }}>
        {kind === "age"
          ? "Items already past the age are replaced in the first period. With the costs, the forecast adds what the strategy costs a year."
          : "With the cost of a failure, the forecast adds what failures cost a year."}
      </p>
    </>
  );
}

// The strategy's answer: failures, planned replacements, parts and cost, by year.
export default function FleetStrategyCard({ forecast }) {
  const st = forecast?.strategy;
  if (!st || !st.total) return null;
  const currency = workspaceCurrency();
  const age = st.kind === "age";
  const unit = unitInText(forecast.unit || "");
  const word = String(forecast.period_label || "periods").replace(/s$/, "");
  const horizon = `${forecast.periods} ${Number(forecast.periods) === 1 ? word : forecast.period_label}`;
  const priced = !!st.total.cost;
  const cost = (b) => (b ? formatCost(b.expected, currency, { sig: 3 }) : "—");
  const costRange = (b) => (b ? rangeText(b, (v) => formatCost(v, currency, { sig: 3 })) : null);
  const count = (b) => formatNumber(b.expected, { sig: 3 });
  const q = firstPeriodsParts(st, forecast.period_label);
  const level = rangeLevelText(forecast.interval_level);
  const years = (st.yearly || []).filter((y) => y);

  return (
    <div className="card" style={{ marginTop: "1rem" }} data-testid="fleet-strategy">
      <CardHeader
        title={age ? `Replace at ${formatWithUnit(st.replace_at, unit)}` : "Run to failure"}
        subtitle={age
          ? "Failures and planned replacements over the horizon, the parts they need and what they cost."
          : "Failures over the horizon and what they cost."}
      />
      <ResultSummary
        sentence={age ? (
          <>
            ≈ <b>{count(st.total.planned)}</b> planned replacements and <b>{count(st.total.failures)}</b> failures in
            the next <b>{horizon}</b>: about <b>{count(st.total.parts)}</b> parts
            {priced && <>, costing about <b>{cost(st.total.cost)}</b></>}.
          </>
        ) : (
          <>
            ≈ <b>{count(st.total.failures)}</b> failures in the next <b>{horizon}</b>
            {priced && <>, costing about <b>{cost(st.total.cost)}</b></>}.
          </>
        )}
        stats={[
          priced && { label: `Cost (${level})`, value: costRange(st.total.cost) },
          age && st.catch_up > 0 && { label: "Already past the age", value: `${st.catch_up}`, hint: `replaced in ${word} 1` },
          q && { label: `Parts, first ${q.periods} ${q.periods === 1 ? word : forecast.period_label}`,
                 value: `≈ ${formatNumber(q.parts, { sig: 3 })}` },
        ]}
      >
        {age && "Planned replacements are known ahead, so their parts can be ordered to arrive in time."}
      </ResultSummary>
      {years.length > 0 && (
        <ScrollCue className="table-scroll">
          <table className="mini-table" data-testid="fleet-strategy-years">
            <thead>
              <tr>
                <th>Year</th>
                <th className="num">Failures</th>
                {age && <th className="num">Planned</th>}
                {age && <th className="num">Parts</th>}
                {priced && <th className="num">Cost</th>}
                {priced && <th className="num">Likely range ({level})</th>}
              </tr>
            </thead>
            <tbody>
              {years.map((y) => (
                <tr key={y.year}>
                  <td>
                    Year {y.year}
                    <span className="hint"> ({word}s {y.from_period}–{y.to_period}{y.complete ? "" : ", part year"})</span>
                  </td>
                  <td className="num">{count(y.failures)}</td>
                  {age && <td className="num">{count(y.planned)}</td>}
                  {age && <td className="num">{count(y.parts)}</td>}
                  {priced && <td className="num">{cost(y.cost)}</td>}
                  {priced && <td className="num">{costRange(y.cost)}</td>}
                </tr>
              ))}
            </tbody>
          </table>
        </ScrollCue>
      )}
      <p className="rs-note">
        From the forecast's simulation: each item's remaining life given its use, then new ones' lives
        {age ? `, each cut short at ${formatWithUnit(st.replace_at, unit)}` : ""}. Ranges are {level}.
        {!priced && " Add the cost of a failure (and of a planned replacement) under Change settings for a budget."}
      </p>
    </div>
  );
}
