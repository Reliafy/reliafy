// A fleet forecast's spares answer (#31, #297): the replacement part's lead time
// and service level (saved with the fleet, in its periods) give how many to hold,
// when to reorder and the chance the stock in hand runs out, read off the
// forecast's own distribution.
import { formatNumber } from "../format.js";
import { money } from "../maintenanceForecast.js";
import { CardHeader } from "./ui/Card.jsx";
import SparesWhatIf from "./SparesWhatIf.jsx";
import { SERVICE_LEVELS, fleetSparesCsv, levelText, overText, riskText, saveText } from "../sparesPlan.js";

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
  const ok = answer?.status === "ok";
  const over = overText(answer?.repairable, answer?.review);
  return (
    <div className="card" style={{ marginTop: "1rem" }} data-testid="fleet-spares">
      <CardHeader title="Spares: how many to hold"
                  subtitle="For the replacement part: the stock that covers the lead time at your service level, from this forecast's own distribution." />
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
        {field("unit_cost", "Cost each")}
      </div>
      <div className="row" style={{ gap: "0.8rem", alignItems: "flex-end", flexWrap: "wrap" }}>
        <label className="maint-row" style={{ gap: "0.4rem", marginTop: 0 }}>
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
          <p data-testid="fleet-spares-summary">{answer.summary}</p>
          <div className="maint-scroll"><table className="lib-table">
            <tbody>
              <tr><th>Hold</th><td><b>{formatNumber(answer.hold)}</b>
                {answer.hold_cost != null && <span className="lib-date"> ({money(answer.hold_cost)})</span>}</td></tr>
              <tr><th>Reorder at</th><td>{answer.reorder_at == null ? "repair each one"
                : answer.reorder_at >= answer.hold ? "one for one: replace each as it’s used" : formatNumber(answer.reorder_at)}</td></tr>
              <tr><th>Expected use over {over}</th><td>≈ {formatNumber(answer.expected_demand, { sig: 2 })}</td></tr>
              {answer.stock != null && (
                <tr><th>With {formatNumber(answer.stock)} in stock</th>
                  <td className={answer.below_reorder ? "maint-overdue" : undefined}>
                    {riskText(answer.risk_at_stock)} chance of running out
                    {answer.to_order > 0 ? `; order ${formatNumber(answer.to_order)}` : ""}</td></tr>
              )}
            </tbody>
          </table></div>
          <SparesWhatIf curve={answer.risk_curve} over={over} initial={answer.hold} idPrefix="fleet" />
          <details>
            <summary className="lib-date">Stock to hold by {label.replace(/s$/i, "")}</summary>
            <div className="maint-scroll"><table className="lib-table">
              <thead><tr><th>{label[0].toUpperCase() + label.slice(1).replace(/s$/i, "")}</th><th>Expected use over {over}</th><th>Hold</th><th>Reorder at</th></tr></thead>
              <tbody>
                {answer.per_period.map((p) => (
                  <tr key={p.period}><td>{p.period}</td><td className="lib-date">≈ {formatNumber(p.expected_demand, { sig: 2 })}</td>
                    <td>{formatNumber(p.hold)}</td><td>{p.reorder_at == null ? "—" : formatNumber(p.reorder_at)}</td></tr>
                ))}
              </tbody>
            </table></div>
          </details>
          <div className="maint-row">
            <button className="secondary" onClick={() => saveText(fleetSparesCsv(answer, { fleet: fleet.name, periodLabel: label }),
              fileName(fleet.name))}>Export spares plan (CSV)</button>
          </div>
          <p className="rs-note">{answer.basis} {answer.repairable ? "One site: every unit sent for repair comes back." : ""}</p>
        </>
      )}
    </div>
  );
}
