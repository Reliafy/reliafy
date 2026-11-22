// A fleet forecast's spares answer (#31, #297): the replacement part's lead time
// and service level (saved with the fleet, in its periods) give how many to hold,
// when to reorder and the chance the stock in hand runs out, read off the
// forecast's own distribution.
import { Link } from "react-router-dom";
import { formatNumber } from "../format.js";
import { money } from "../maintenanceForecast.js";
import { costLabel, prefixCurrency, workspaceCurrency } from "../money.js";
import { CardHeader } from "./ui/Card.jsx";
import ResultSummary from "./ui/ResultSummary.jsx";
import SparesWhatIf from "./SparesWhatIf.jsx";
import { SERVICE_LEVELS, fleetSparesCsv, holdText, leadTimeHint, levelText, overText, riskText, risingText, saveText, useText, yearText } from "../sparesPlan.js";

const blank = (v) => v === null || v === undefined || v === "";
const fileName = (name) => `${String(name).replace(/[^\w\- ]+/g, "").trim() || "fleet"} — spares plan.csv`;

// A fleet's spares question and answer: the replacement part's lead time and
// service level (saved with the fleet, in its periods) → how many to hold.
export default function FleetSparesCard({ fleet, settings, forecast, readOnly, dirty, onChange }) {
  const sp = settings.spares || {};
  const label = String(settings.period_label || "periods");
  const answer = !dirty ? forecast.spares : null;
  const set = (key, value) => onChange({ ...sp, [key]: value === "" ? null : value });
  const field = (key, text, extra = {}) => (
    <label className="login-field" style={{ width: 150 }}>
      <span>{text}</span>
      {readOnly ? <span>{blank(sp[key]) ? "—" : formatNumber(sp[key], { sig: 6 })}</span> : (
        <input type="number" inputMode="decimal" min="0" step="any" value={sp[key] ?? ""}
               onChange={(e) => set(key, e.target.value)} {...extra} />
      )}
    </label>
  );
  const leadHint = leadTimeHint(sp.lead_time, label);
  const ok = answer?.status === "ok";
  const over = overText(answer?.repairable, answer?.review);
  return (
    <div className="card mt-4" data-testid="fleet-spares">
      <CardHeader title="Spares: how many to hold"
                  subtitle="For the replacement part: the stock that covers the lead time at your service level, from this forecast's own distribution." />
      <p className="hint" data-testid="fleet-spares-when-to-use" style={{ margin: "0 0 0.6rem" }}>
        Use this for a fleet of individual items with known ages and a life model, with a lead time. For a stream of
        replacements counted as one process, such as a fleet's replacements against fleet hours, use the Calculator's
        stock to hold on a <Link to="/models/recurrent">repairable model</Link>.
      </p>
      <div className="row" style={{ gap: "0.8rem", alignItems: "flex-end", flexWrap: "wrap", marginTop: 0 }}>
        {field("lead_time", `Lead time (${label})`, { placeholder: "required" })}
        <label className="login-field" style={{ width: 150 }}>
          <span>Service level</span>
          <select value={sp.service_level ?? ""} disabled={readOnly}
                  onChange={(e) => set("service_level", e.target.value === "" ? "" : Number(e.target.value))}>
            <option value="">95% (default)</option>
            {SERVICE_LEVELS.map((l) => <option key={l} value={l}>{levelText(l)}</option>)}
          </select>
        </label>
        {field("review", `Review every (${label})`, { placeholder: "0" })}
        {field("per_failure", "Parts per failure", { placeholder: "1" })}
        {field("stock", "In stock now")}
        {field("unit_cost", costLabel("Cost each", workspaceCurrency()))}
      </div>
      {!readOnly && leadHint && <p className="hint" data-testid="fleet-spares-lead-hint" style={{ margin: "0.4rem 0 0" }}>Lead time: {leadHint}.</p>}
      <div className="row" style={{ gap: "0.8rem", alignItems: "flex-end", flexWrap: "wrap" }}>
        <label style={{ display: "flex", alignItems: "center", gap: "0.4rem" }}>
          <input type="checkbox" checked={!!sp.repairable} disabled={readOnly}
                 onChange={(e) => set("repairable", e.target.checked || null)} />
          Repairable: failed ones are repaired and come back
        </label>
        {sp.repairable && field("turnaround", `Repair turnaround (${label})`)}
      </div>
      {dirty && <p className="lib-date">Save &amp; forecast to update the answer.</p>}
      {!dirty && !answer && (
        <p className="lib-date">Set the replacement part’s lead time, then Save &amp; forecast.</p>
      )}
      {answer && !ok && <p className="lib-date">{answer.summary || answer.reason}</p>}
      {ok && (
        <>
          <ResultSummary
            sentence={<span data-testid="fleet-spares-summary">{answer.summary}</span>}
            tone={answer.below_reorder ? "caveat" : "neutral"}
            stats={[
              { label: answer.repairable ? "Pool" : "Hold", value: holdText(answer),
                hint: [risingText(answer, label), answer.hold_cost != null ? prefixCurrency(money(answer.hold_cost)) : null]
                  .filter(Boolean).join(" · ") || undefined },
              { label: "Reorder at",
                value: answer.reorder_at == null ? "repair each"
                  : !answer.review && answer.hold > 0 && answer.reorder_at >= answer.hold ? "one for one"
                    : formatNumber(answer.reorder_at) },
              { label: "Expected use", value: useText(answer.expected_demand), hint: `over ${over}` },
              answer.stock != null && {
                label: `Runs out with ${formatNumber(answer.stock)}`, value: riskText(answer.risk_at_stock),
                hint: answer.to_order > 0 ? `order ${formatNumber(answer.to_order)}` : undefined,
              },
            ]}
          />
          {answer.year && <YearAnswer year={answer.year} />}
          <SparesWhatIf curve={answer.risk_curve} over={over} initial={answer.hold} idPrefix="fleet" />
          <details>
            <summary className="lib-date">Stock to hold by {label.replace(/s$/i, "")}</summary>
            <div className="maint-scroll"><table className="mini-table spares-by-period">
              <thead><tr><th>{label[0].toUpperCase() + label.slice(1).replace(/s$/i, "")}</th><th>Expected use over {over}</th><th>Hold</th><th>Reorder at</th></tr></thead>
              <tbody>
                {answer.per_period.map((p) => (
                  <tr key={p.period}><td className="num">{p.period}</td><td className="num">{useText(p.expected_demand)}</td>
                    <td className="num">{formatNumber(p.hold)}</td><td className="num">{p.reorder_at == null ? "—" : formatNumber(p.reorder_at)}</td></tr>
                ))}
              </tbody>
            </table></div>
          </details>
          <div className="mt-2">
            <button className="secondary" onClick={() => saveText(fleetSparesCsv(answer, { fleet: fleet.name, periodLabel: label }),
              fileName(fleet.name))}>Export spares plan (CSV)</button>
          </div>
          <p className="rs-note">{answer.basis} {answer.repairable ? "One site: every unit sent for repair comes back." : ""}</p>
        </>
      )}
    </div>
  );
}

// The answer for the whole forecast (spares for the year): the demand, what to
// order now and what to buy over it, with the rule it follows. Prices stay in
// your own budget: this gives the quantities.
function YearAnswer({ year }) {
  const rows = [
    ["Needed over the forecast", yearText(year)],
    year.order_now != null && ["Order now", formatNumber(year.order_now)],
    year.buy != null && ["Buy over the forecast", `${formatNumber(year.buy)} (high case ${formatNumber(year.buy_high_case)})`],
  ].filter(Boolean);
  return (
    <div className="maint-scroll" data-testid="fleet-spares-year">
      <table className="mini-table">
        <tbody>
          {rows.map(([k, v]) => <tr key={k}><th scope="row">{k}</th><td>{v}</td></tr>)}
        </tbody>
      </table>
      {year.buy == null && year.order_now == null && <p className="hint">Enter what’s in stock now to see what to order and buy.</p>}
      <p className="hint">{year.rule} The high case uses the 90th percentile of the demand.</p>
    </div>
  );
}
