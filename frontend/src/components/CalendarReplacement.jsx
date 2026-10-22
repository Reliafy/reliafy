import { useEffect, useRef, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import ModelPicker from "./ModelPicker.jsx";
import Select from "./Select.jsx";
import CalendarReplacementResult from "./CalendarReplacementResult.jsx";
import { calendarNext, calendarReplacement, getRbdJob } from "../api.js";
import { modelFromSearch } from "../modelNext.js";
import { formatNumber } from "../format.js";
import { unitInText } from "./unitText.js";
import {
  EVERY_UNITS, METHODS, TIME_UNITS, buildRequest, formatDate, localToday, newShut, timeUnit,
} from "../calendarReplacement.js";
import "./CalendarReplacement.css";

const POLL_FIRST_MS = 1500;
const POLL_MAX_MS = 6000;

// Strategy › Replacement, "Shutdown calendar": when replacing costs less at the
// shuts than between them, the long-run best rule (replace at a shut if the
// part is older than a threshold age), what simpler rules cost, and the next
// months by date; then one unit in service: now, at the next shut, or later.
// Today is time 0; the server turns the dates into model time.
export default function CalendarReplacement() {
  const today0 = useRef(localToday()).current;
  const wanted = modelFromSearch(useLocation().search);
  const [model, setModel] = useState(null);
  const [unit, setUnit] = useState("");
  const [today, setToday] = useState(today0);
  const [shuts, setShuts] = useState(() => [newShut(today0)]);
  const [failureCost, setFailureCost] = useState("");
  const [anytimeCost, setAnytimeCost] = useState("");
  const [maxAge, setMaxAge] = useState("");
  const [method, setMethod] = useState("dp");
  const [result, setResult] = useState(null);
  const [body, setBody] = useState(null); // what produced the result
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);
  const [needsPro, setNeedsPro] = useState(false);
  const [job, setJob] = useState(null);

  const pickModel = (m) => {
    setModel(m);
    if (m?.unit && timeUnit(m.unit)) setUnit(timeUnit(m.unit));
  };
  const setShut = (i, patch) => setShuts((list) => list.map((s, j) => (j === i ? { ...s, ...patch } : s)));
  const u = unitInText(unit || "");

  const run = async () => {
    const built = buildRequest({ model, unit, today, shuts, failureCost, anytimeCost, maxAge, method });
    setNeedsPro(false);
    setJob(null);
    if (built.error) { setError(built.error); return; }
    setLoading(true);
    setError(null);
    try {
      const out = await calendarReplacement(built.body);
      if (out.job) { setJob(out.job); setBody(built.body); return; }
      setResult(out);
      setBody(built.body);
      setLoading(false);
    } catch (err) {
      setLoading(false);
      setResult(null);
      if (err.status === 402 && err.code === "pro_required") setNeedsPro(true);
      else setError(err.message);
    }
  };

  // Poll a queued (sampled) run until it's done.
  const jobId = job?.job_id;
  useEffect(() => {
    if (!jobId) return undefined;
    let cancelled = false;
    let timer = null;
    let delay = POLL_FIRST_MS;
    let failures = 0;
    const poll = async () => {
      try {
        const view = await getRbdJob(jobId);
        if (cancelled) return;
        failures = 0;
        if (view.status === "done") { setJob(null); setResult(view.result); setLoading(false); return; }
        if (view.status === "failed") {
          setJob(null); setLoading(false); setError(view.error || "The calculation failed.");
          return;
        }
        setJob((prev) => (prev && prev.job_id === jobId ? { ...prev, ...view } : prev));
      } catch (err) {
        if (cancelled) return;
        if (err.status === 404 || ++failures >= 6) {
          setJob(null); setLoading(false);
          setError(err.status === 404 ? "The calculation was lost — run it again." : err.message);
          return;
        }
      }
      delay = Math.min(delay * 1.3, POLL_MAX_MS);
      timer = setTimeout(poll, delay);
    };
    timer = setTimeout(poll, POLL_FIRST_MS);
    return () => { cancelled = true; clearTimeout(timer); };
  }, [jobId]);

  return (
    <div className="strategy-tool">
      <div className="strategy-form cal-form">
        <ModelPicker key={wanted || ""} label="Non-repairable model" value={model} onChange={pickModel} preferSaved
                     wanted={wanted} />
        <div className="strategy-costs">
          <label className="calc-t">
            <span>Model time unit</span>
            <Select value={unit} onChange={setUnit} ariaLabel="Model time unit" placeholder="Choose…"
                    options={TIME_UNITS.map((t) => ({ value: t, label: t }))} />
          </label>
          <label className="calc-t">
            <span>Today (time 0)</span>
            <input type="date" value={today} onChange={(e) => setToday(e.target.value || today0)} />
          </label>
        </div>

        <h3 className="cal-h">Shuts</h3>
        <p className="muted-line">Times when replacing the part is cheaper: shutdowns, turnarounds, weekly stops.</p>
        <div className="cal-shuts">
          {shuts.map((s, i) => (
            <fieldset key={i} className="cal-shut" aria-label={`Shut ${i + 1}`}>
              <label className="calc-t">
                <span>Name</span>
                <input type="text" value={s.name} onChange={(e) => setShut(i, { name: e.target.value })} />
              </label>
              <label className="calc-t">
                <span>Replacing at it costs</span>
                <input type="number" inputMode="decimal" min="0" step="any" value={s.cost}
                       onChange={(e) => setShut(i, { cost: e.target.value })} />
              </label>
              <label className="calc-t">
                <span>When</span>
                <Select value={s.how} onChange={(v) => setShut(i, { how: v })} ariaLabel={`When ${s.name} comes`}
                        options={[{ value: "every", label: "Repeats" }, { value: "dates", label: "On dates" }]} />
              </label>
              {s.how === "dates" ? (
                <label className="calc-t cal-dates">
                  <span>Dates (YYYY-MM-DD, one per line)</span>
                  <textarea rows={3} value={s.dates} onChange={(e) => setShut(i, { dates: e.target.value })} />
                </label>
              ) : (
                <>
                  <label className="calc-t cal-every">
                    <span>Every</span>
                    <span className="cal-every-row">
                      <input type="number" inputMode="decimal" min="0" step="any" value={s.every}
                             aria-label={`Every how many ${s.everyUnit}`}
                             onChange={(e) => setShut(i, { every: e.target.value })} />
                      <Select value={s.everyUnit} onChange={(v) => setShut(i, { everyUnit: v })}
                              ariaLabel="Every unit" options={EVERY_UNITS.map((x) => ({ value: x, label: x }))} />
                    </span>
                  </label>
                  <label className="calc-t">
                    <span>Starting</span>
                    <input type="date" value={s.start} onChange={(e) => setShut(i, { start: e.target.value })} />
                  </label>
                </>
              )}
              {shuts.length > 1 && (
                <button type="button" className="link sm cal-remove"
                        onClick={() => setShuts((list) => list.filter((_, j) => j !== i))}>Remove</button>
              )}
            </fieldset>
          ))}
        </div>
        {shuts.length < 8 && (
          <button type="button" className="secondary sm"
                  onClick={() => setShuts((list) => [...list, newShut(today, list.length)])}>Add a shut</button>
        )}

        <div className="strategy-costs">
          <label className="calc-t">
            <span>Failure (unplanned) cost</span>
            <input type="number" inputMode="decimal" min="0" step="any" value={failureCost}
                   onChange={(e) => setFailureCost(e.target.value)} />
          </label>
          <label className="calc-t">
            <span>Replacing between shuts costs</span>
            <input type="number" inputMode="decimal" min="0" step="any" value={anytimeCost} placeholder="not allowed"
                   onChange={(e) => setAnytimeCost(e.target.value)} />
          </label>
        </div>
        <details className="cal-advanced">
          <summary>Method and limits</summary>
          <div className="strategy-costs">
            <label className="calc-t">
              <span>Method</span>
              <Select value={method} onChange={setMethod} ariaLabel="Method"
                      options={METHODS.map((m) => ({ value: m.value, label: m.label, hint: m.hint }))} />
            </label>
            <label className="calc-t">
              <span>Oldest age to consider{u ? ` (${u})` : ""}</span>
              <input type="number" inputMode="decimal" min="0" step="any" value={maxAge} placeholder="automatic"
                     onChange={(e) => setMaxAge(e.target.value)} />
            </label>
          </div>
        </details>
        <p className="muted-line">
          Today ({formatDate(today)}) is time 0. Dates become model time at 24 hours, 7 days, an average month
          (365.25/12 days) or 365.25 days per unit.
        </p>
        <div className="strategy-costs">
          <button onClick={run} disabled={loading}>{loading ? "Computing…" : "Compute"}</button>
        </div>
      </div>

      {loading && job && (
        <p className="hint" role="status" aria-live="polite">
          {job.status === "running" ? "Sampling the calendar…"
            : job.queue_position ? `Queued for the calculation service (${job.queue_position} ahead)…`
              : "Queued for the calculation service…"}
        </p>
      )}
      {needsPro && (
        <div className="card note" role="status">
          <p style={{ margin: 0 }}>
            <b>Sampling is part of Pro.</b> It runs the calendar many times on Reliafy's calculation service. The
            exact methods are free.
          </p>
          <div className="rbd-upgrade-actions"><Link className="cta cta-solid" to="/billing">Upgrade to Pro</Link></div>
        </div>
      )}
      {error && <div className="error">{error}</div>}

      {result && (
        <>
          <CalendarReplacementResult result={result} wt="cal-result" />
          {body && <UnitNow body={body} unit={result.unit} />}
        </>
      )}
    </div>
  );
}

// One unit in service: its age today → replace now, at the next shut, between
// shuts, or run it to failure (always the exact method: free).
function UnitNow({ body, unit }) {
  const [age, setAge] = useState("");
  const [nowCost, setNowCost] = useState("");
  const [out, setOut] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const u = unitInText(unit);

  const check = async () => {
    if (age === "" || !(Number(age) >= 0)) { setError("Enter the unit's age."); return; }
    setBusy(true); setError(null);
    try {
      const { method, ...rest } = body; // eslint-disable-line no-unused-vars
      setOut(await calendarNext({ ...rest, age: Number(age), now_cost: nowCost === "" ? null : Number(nowCost) }));
    } catch (err) { setError(err.message); setOut(null); } finally { setBusy(false); }
  };

  return (
    <section className="cal-block cal-now cal-form" data-testid="calendar-unit-now">
      <h3>One unit now</h3>
      <p className="muted-line">The unit in service: replace it now, at the next shut, or later?</p>
      <div className="strategy-costs">
        <label className="calc-t">
          <span>Its age today ({u})</span>
          <input type="number" inputMode="decimal" min="0" step="any" value={age}
                 onChange={(e) => setAge(e.target.value)} />
        </label>
        <label className="calc-t">
          <span>Replacing it now costs</span>
          <input type="number" inputMode="decimal" min="0" step="any" value={nowCost} placeholder="default"
                 onChange={(e) => setNowCost(e.target.value)} />
        </label>
        <button className="secondary" onClick={check} disabled={busy}>{busy ? "Checking…" : "Check this unit"}</button>
      </div>
      {error && <div className="error">{error}</div>}
      {out && (
        <>
          <p className="cal-now-answer"><b>{out.recommendation}</b></p>
          <div className="table-scroll">
            <table className="mini-table">
              <thead><tr><th>Choice</th><th>Price</th><th>Expected cost</th><th>Replacing now beats it from age</th></tr></thead>
              <tbody>
                {out.choices.map((c, i) => (
                  <tr key={i} className={c === out.best || (c.kind === out.best.kind && c.time === out.best.time) ? "cal-best" : ""}>
                    <td>{c.label}</td>
                    <td>{formatNumber(c.price)}</td>
                    <td>{formatNumber(c.cost, { sig: 4 })}</td>
                    <td>{c.kind === "now" ? "—" : c.break_even_age == null ? "never" : `${formatNumber(c.break_even_age)} ${u}`}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {out.policy_next && <p className="muted-line">{out.policy_next.text}</p>}
          <p className="muted-line">
            Each cost is what this unit costs until it's replaced, less the value of the time it serves at the
            calendar's long-run rate ({formatNumber(out.cost_per_year)} a year). Lower is better; only the
            differences matter.
          </p>
        </>
      )}
    </section>
  );
}
