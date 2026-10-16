// A position class's spares stock levels (#31), on its failure forecast: how many
// of each part to hold for a service level over its lead time, when to reorder,
// the chance today's stock runs out, the plan by period and its CSV, and each
// part's own settings (lead time, service level, repairable with a turnaround).
import { useState } from "react";
import { updateMaintenancePart } from "../api.js";
import { Field, FormModal } from "./MaintenanceParts.jsx";
import SparesWhatIf from "./SparesWhatIf.jsx";
import { formatNumber } from "../format.js";
import { money, periodLabels } from "../maintenanceForecast.js";
import { SERVICE_LEVELS, levelText, overText, riskText, saveText, stockingCsv, windowText } from "../sparesPlan.js";

const blank = (v) => v === null || v === undefined || v === "";
const num = (v) => (blank(v) ? null : Number(v));
const fileName = (name) => `${String(name).replace(/[^\w\- ]+/g, "").trim() || "spares"} — stocking plan.csv`;

// One part's stock-level settings, kept on the part.
function PartStockingModal({ spare, onClose, onDone }) {
  const own = spare.stocking?.part_settings || {};
  const [f, setF] = useState({
    lead_time_days: own.lead_time_days ?? "", service_level: own.service_level ?? "",
    repairable: !!own.repairable, turnaround_days: own.turnaround_days ?? "", unit_cost: spare.part.unit_cost ?? "",
  });
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });
  return (
    <FormModal title={`Stock levels: ${spare.part.part_number}`} submitLabel="Save" onClose={onClose}
               onSubmit={async () => onDone(await updateMaintenancePart(spare.part.id, {
                 lead_time_days: num(f.lead_time_days), service_level: num(f.service_level),
                 repairable: f.repairable, turnaround_days: f.repairable ? num(f.turnaround_days) : null,
                 unit_cost: num(f.unit_cost),
               }))}>
      <Field label="Lead time to replenish (days)">
        <input autoFocus type="number" inputMode="decimal" min="0" step="any" value={f.lead_time_days}
               placeholder="30 assumed" onChange={set("lead_time_days")} />
      </Field>
      <Field label="Service level (chance of no stock-out)">
        <select value={f.service_level} onChange={set("service_level")}>
          <option value="">Default (95%)</option>
          {SERVICE_LEVELS.map((l) => <option key={l} value={l}>{levelText(l)}</option>)}
        </select>
      </Field>
      <label className="maint-row" style={{ gap: "0.4rem", marginTop: 0 }}>
        <input type="checkbox" checked={f.repairable} onChange={(e) => setF({ ...f, repairable: e.target.checked })} />
        Repairable: failed ones are repaired and come back
      </label>
      {f.repairable && (
        <Field label="Repair turnaround (days)">
          <input type="number" inputMode="decimal" min="0" step="any" value={f.turnaround_days}
                 onChange={set("turnaround_days")} />
        </Field>
      )}
      <Field label="Cost each (optional)">
        <input type="number" inputMode="decimal" min="0" step="any" value={f.unit_cost} onChange={set("unit_cost")} />
      </Field>
      <p className="lib-date">
        Hold covers the lead time (plus the review period). A repairable part’s pool covers its repair turnaround
        instead: one site, every unit sent comes back.
      </p>
    </FormModal>
  );
}

// The class forecast's stock levels: a table of the parts, a what-if, the plan
// by period for one part, and the CSV of the whole plan.
export function ClassStocking({ data, name, serviceLevel, reviewDays, onOptions, onChanged }) {
  const [editing, setEditing] = useState(null);
  const [review, setReview] = useState(reviewDays || "");
  const rows = (data.spares || []).filter((s) => s.stocking);
  const [pick, setPick] = useState(null);
  const chosen = rows.find((s) => s.part.id === pick) || rows[0];
  const meta = data.stocking || {};
  const labels = chosen ? periodLabels(chosen.stocking.per_period, data.period) : [];
  const commitReview = () => {
    if (String(review) !== String(reviewDays || "")) onOptions({ reviewDays: review });
  };
  if (!data.spares?.length) return null;
  return (
    <div data-testid="spares-stocking">
      <h3 className="maint-sub">Stock to hold</h3>
      <div className="maint-row" style={{ marginTop: 0, flexWrap: "wrap", gap: "0.5rem" }}>
        <label className="lib-date" htmlFor="stock-sl">Service level</label>
        <select id="stock-sl" value={serviceLevel || ""} onChange={(e) => onOptions({ serviceLevel: e.target.value })}>
          <option value="">Each part’s own (default 95%)</option>
          {SERVICE_LEVELS.map((l) => <option key={l} value={l}>{levelText(l)} for every part</option>)}
        </select>
        <label className="lib-date" htmlFor="stock-review">Stock checked every</label>
        <input id="stock-review" type="number" inputMode="decimal" min="0" step="any" value={review}
               placeholder="0" style={{ width: "4.5rem" }} onChange={(e) => setReview(e.target.value)}
               onBlur={commitReview} onKeyDown={(e) => { if (e.key === "Enter") commitReview(); }} />
        <span className="lib-date">days</span>
      </div>
      {meta.error ? <div className="card error">{meta.error}</div> : (
        <div className="maint-scroll"><table className="lib-table">
          <thead><tr><th>Part</th><th>Hold</th><th>Reorder at</th><th>Usable now</th><th>Chance it runs out</th><th>Covers</th><th /></tr></thead>
          <tbody>
            {rows.map((s) => {
              const st = s.stocking;
              return (
                <tr key={s.part.id} title={st.summary}>
                  <td>{s.part.part_number} {s.part.name}</td>
                  <td><b>{formatNumber(st.hold)}</b>
                    {st.hold_cost != null && <span className="lib-date"> ({money(st.hold_cost)})</span>}</td>
                  <td>{st.reorder_at == null ? <span className="lib-date">repair each</span>
                    : !st.review_days && st.hold > 0 && st.reorder_at >= st.hold ? <span className="lib-date">one for one</span> : formatNumber(st.reorder_at)}</td>
                  <td>{formatNumber(s.usable_on_hand)}
                    {st.below_reorder && <span className="maint-overdue"> {st.repairable ? "short" : "reorder now"}</span>}</td>
                  <td className={st.risk_at_stock > 1 - st.service_level + 1e-9 ? "maint-overdue" : undefined}>
                    {riskText(st.risk_at_stock)}</td>
                  <td className="lib-date">{windowText(st)} at {levelText(st.service_level)}</td>
                  <td><button className="secondary sm" onClick={() => setEditing(s)}
                              aria-label={`Stock levels for ${s.part.part_number}`}>Set</button></td>
                </tr>
              );
            })}
          </tbody>
        </table></div>
      )}
      {chosen && (
        <>
          {rows.length > 1 && (
            <p className="maint-row lib-date" style={{ gap: "0.4rem" }}>
              <label htmlFor="stock-part">Part</label>
              <select id="stock-part" value={chosen.part.id} onChange={(e) => setPick(e.target.value)}>
                {rows.map((s) => <option key={s.part.id} value={s.part.id}>{s.part.part_number} {s.part.name}</option>)}
              </select>
            </p>
          )}
          <p data-testid="spares-summary">{chosen.stocking.summary}</p>
          <SparesWhatIf curve={chosen.stocking.risk_curve} unit={chosen.unit} initial={chosen.stocking.hold}
                  over={overText(chosen.stocking.repairable, chosen.stocking.review_days)} idPrefix="class" />
          <details>
            <summary className="lib-date">Stock to hold by {data.period} ({chosen.part.part_number})</summary>
            <div className="maint-scroll"><table className="lib-table">
              <thead><tr><th>{data.period[0].toUpperCase() + data.period.slice(1)} starting</th><th>Expected use that {data.period}</th><th>Hold</th><th>Reorder at</th></tr></thead>
              <tbody>
                {chosen.stocking.per_period.map((p, i) => (
                  <tr key={p.start}>
                    <td>{labels[i]}</td>
                    <td className="lib-date">≈ {formatNumber(chosen.per_period[i]?.mean ?? 0, { sig: 2 })}</td>
                    <td>{formatNumber(p.hold)}</td>
                    <td>{p.reorder_at == null ? "—" : formatNumber(p.reorder_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table></div>
          </details>
        </>
      )}
      <div className="maint-row" style={{ flexWrap: "wrap", gap: "0.5rem" }}>
        <button className="secondary" onClick={() => saveText(stockingCsv(data.spares, { positionClass: name, period: data.period }),
          fileName(name))}>Export stocking plan (CSV)</button>
      </div>
      {meta.note && <p className="lib-date">{meta.note}</p>}
      {editing && <PartStockingModal spare={editing} onClose={() => setEditing(null)}
                                     onDone={() => { setEditing(null); onChanged(); }} />}
    </div>
  );
}
