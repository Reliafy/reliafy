import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { getForecastDetails } from "../api.js";
import { promptGroups } from "../failureCosts.js";
import { formatChance } from "../format.js";
import {
  BASES, CAL_HORIZONS, HOURS_HORIZONS, bars, columns, detailsCsv, detailsQuery, emptyColumns, everyFor, groupsFor, horizonText,
  meterText, pageOf, rowLabel, whatText, whenText,
} from "../forecastDetails.js";
import { costRangeText, dayText, failuresText, hoursText, moneyText, sig } from "../positionForecast.js";
import { saveText } from "../sparesPlan.js";
import { tabPlace } from "../explorerTabs.js";
import { ShowMe } from "./SectionPage.jsx";
import ChoiceChips from "./ui/ChoiceChips.jsx";
import SegmentedControl from "./ui/SegmentedControl.jsx";
import Field from "./ui/Field.jsx";
import { DateInput } from "./ui/DateTimeInput.jsx";
import { TextInput } from "./ui/Controls.jsx";
import ResultSummary, { ResultDetails } from "./ui/ResultSummary.jsx";
import "./PositionForecast.css";

// The one forecast view (Derryn, 23 Nov 2026): a task's or a package's Forecast row opened, and a
// level's Forecast… (that position and everything inside it), the same component. Choose the basis
// (the calendar, or running hours: "with or without a duty"), the horizon and the grouping; then the
// answer first, the counts as bars, the table of counts and costs by period with its totals (CSV),
// When next 20 at a time, and what couldn't be placed and why. Worked out by the server
// (backend/maintenance/forecast_details.py, on RePyability); nothing here works out a date.
//
//   positionId  the level (a task's or package's: the position its row is under)
//   root        the asset opened          name  the level's name
//   subject     {kind: level|task|package, taskId?, packageId?, name?}
//   bar         more controls in the view's own bar (the LSA tab's Tasks / Forecast switch)

const DEFAULTS = { months: "12", end: "", group: "month", hours: "1000", every: "100", reading: "" };

// The answer's numbers in bold, after its date ("To 30 Nov 2027: **58** tasks, …").
function boldNumbers(text) {
  const s = String(text || "");
  const at = s.indexOf(": ");
  const head = at < 0 ? "" : s.slice(0, at + 2);
  const parts = s.slice(head.length).split(/(\$?\d[\d,]*(?:\.\d+)?%?)/);
  return [head, ...parts.map((part, i) => (i % 2 ? <b key={i}>{part}</b> : part))];
}

function Bars({ d }) {
  const { counts, max } = bars(d);
  if (!counts.length) return null;
  const word = d.basis === "hours" ? "span of hours" : d.period;
  return (
    <figure className="fcd-chart" aria-label={`Times done each ${word}: ${counts.join(", ")}`}>
      <div className="fcd-chart-head" aria-hidden="true">
        <span>Times done each {word}</span>
        <span className="fcd-chart-max">{max.toLocaleString("en-GB")}</span>
      </div>
      <div className="fcd-bars" role="presentation">
        {counts.map((n, i) => (
          <span key={i} className="fcd-bar" title={`${rowLabel(d, d.rows[i], i)}: ${n.toLocaleString("en-GB")}`}
                style={{ "--fcd-h": `${(n / max) * 100}%` }} />
        ))}
      </div>
      <div className="fcd-chart-foot" aria-hidden="true">
        <span>{rowLabel(d, d.rows[0], 0)}</span>
        {d.rows.length > 1 && <span>{rowLabel(d, d.rows[d.rows.length - 1], d.rows.length - 1)}</span>}
      </div>
    </figure>
  );
}

function WhenNext({ d }) {
  const [page, setPage] = useState(0);
  const key = `${d.basis}:${d.start || ""}:${d.end || ""}:${d.hours || ""}:${(d.occurrences || []).length}`;
  useEffect(() => { setPage(0); }, [key]);
  const p = pageOf(d.occurrences, page);
  return (
    <section className="fcd-next" aria-label="When next">
      <h3 className="fc-enter-title">When next</h3>
      {!p.total ? <p className="lib-date">Nothing falls due in {horizonText(d)}.</p> : (
        <>
          <ol className="td-rows fc-list fcd-next-list" start={p.from}>
            {p.items.map((o, i) => (
              <li key={`${p.from + i}`}>
                <span className="fcd-when">{whenText(d, o)}</span>
                {o.overdue && <span className="pk-overdue"> · overdue, done first</span>}
                <div>{whatText(o)}{d.by_position?.length > 1 || (o.position && d.position && o.position.id !== d.position.id)
                  ? <span className="lib-date"> · {o.position.name}</span> : null}</div>
              </li>
            ))}
          </ol>
          <div className="fcd-pager">
            <span className="lib-date" aria-live="polite">{p.from.toLocaleString("en-GB")}–{p.to.toLocaleString("en-GB")} of {p.total.toLocaleString("en-GB")}{d.occurrences_cut ? " (the first 5,000)" : ""}</span>
            <button type="button" className="secondary sm" disabled={p.page === 0} onClick={() => setPage(p.page - 1)}>Previous</button>
            <button type="button" className="secondary sm" disabled={p.page >= p.pages - 1} onClick={() => setPage(p.page + 1)}>Next</button>
          </div>
        </>
      )}
    </section>
  );
}

export default function ForecastDetails({ positionId, root = null, name = "", subject = { kind: "level" }, bar = null }) {
  const [basis, setBasis] = useState(null); // null: the server's default (a duty: the calendar)
  const [ctl, setCtl] = useState(DEFAULTS);
  const [state, setState] = useState({ key: null, data: null, error: null });
  const set = (k) => (v) => setCtl((c) => ({ ...c, [k]: v }));
  const query = useMemo(() => detailsQuery({ root, subject, basis, ...ctl }), [root, subject.kind, subject.taskId, subject.packageId, basis, ctl]); // eslint-disable-line react-hooks/exhaustive-deps
  const key = `${positionId}:${JSON.stringify(query)}`;
  const waiting = basis === "calendar" && ctl.months === "custom" && !ctl.end;
  useEffect(() => {
    if (waiting) return undefined;
    let live = true;
    getForecastDetails(positionId, query)
      .then((data) => {
        if (!live) return;
        setState({ key, data, error: null });
        if (!basis) setBasis(data.basis);
      })
      .catch((e) => live && setState({ key, data: null, error: e.message }));
    return () => { live = false; };
  }, [key, waiting]); // eslint-disable-line react-hooks/exhaustive-deps
  // The last answer stays up while the next is worked out (no flash), marked busy.
  const d = state.data;
  const busy = !waiting && state.key !== key;
  const error = state.key === key ? state.error : null;
  const cols = d ? columns(d) : [];
  const groups = d?.prompts ? promptGroups(d.prompts) : [];
  const left = d ? [...(d.not_placed || []), ...(d.not_forecast || []).map((x) => ({ ...x, life: true }))] : [];
  const shownBasis = basis || d?.basis || "calendar";
  const what = subject.kind === "task" ? "this task" : subject.kind === "package" ? "this package" : `${name || "here"} and everything inside it`;
  const csvName = `forecast-${(subject.name || name || "here").toLowerCase().replace(/[^a-z0-9]+/g, "-")}.csv`;

  return (
    <section className="fc-view fcd" aria-label="Forecast" aria-busy={busy || undefined}>
      <div className="fcd-controls">
        <SegmentedControl size="sm" showLabel label="Basis" value={shownBasis} onChange={(v) => setBasis(v)} options={BASES} />
        {shownBasis === "calendar" ? (
          <>
            <Field label="Horizon" as="fieldset" className="fcd-field">
              <ChoiceChips label="Horizon" value={ctl.months} onChange={(v) => v && set("months")(v)} options={CAL_HORIZONS} />
            </Field>
            {ctl.months === "custom" && (
              <div className="fcd-range">
                <span className="lib-date">From today{d?.today ? `, ${dayText(d.today)}` : ""}, to</span>
                <DateInput value={ctl.end} min={d?.today || undefined} onChange={(e) => set("end")(e.target.value)} aria-label="Last day of the forecast" />
              </div>
            )}
            <SegmentedControl size="sm" showLabel label="Group by" value={ctl.group} onChange={set("group")} options={groupsFor(ctl.months === "custom" ? 120 : ctl.months)} />
          </>
        ) : (
          <>
            <Field label="Horizon" as="fieldset" className="fcd-field">
              <ChoiceChips label="Horizon" value={ctl.hours} onChange={(v) => v && set("hours")(v)} options={HOURS_HORIZONS} />
            </Field>
            <SegmentedControl size="sm" showLabel label="Group every" value={ctl.every} onChange={set("every")} options={everyFor(ctl.hours)} />
            <Field label="Meter now" optional help="The hours reading to count from; blank: the latest recorded" className="fcd-field fcd-reading">
              <TextInput inputMode="decimal" value={ctl.reading} placeholder={d?.reading != null ? sig(d.reading) : ""}
                         onChange={(e) => set("reading")(e.target.value.replace(/[^0-9.]/g, ""))} />
            </Field>
          </>
        )}
        <div className="fcd-actions">
          <ShowMe help={{ guide: "forecast-the-maintenance-plan" }} asHelp />
          <button type="button" className="secondary sm" disabled={!d?.rows?.length} onClick={() => saveText(detailsCsv(d), csvName)}>Export CSV</button>
          {bar}
        </div>
      </div>
      {waiting && <p className="lib-date">Pick the last day of the forecast.</p>}
      {error && <div className="card error" role="alert">Couldn&apos;t work out the forecast: {error}</div>}
      {!d && !error && !waiting && <div className="card empty">Working out the forecast…</div>}
      {d && (
        <div className={"fcd-body" + (busy ? " is-busy" : "")}>
          <ResultSummary className="fc-summary" tone={(d.states || []).length || left.length ? "caveat" : "neutral"} sentence={boldNumbers(d.answer)}>
            For {what}, {horizonText(d)}. {d.duty ? `Duty: ${d.duty.text}${d.duty.inherited_from ? `, from ${d.duty.inherited_from.name}` : ""}.` : (
              d.by_use_tasks > 0 || d.basis === "hours" ? (
                <>No duty here, so running hours stay hours{d.basis === "hours" && d.calendar_tasks ? " and calendar rules stay on the calendar" : ""}: <Link to={d.duty_link}>set a duty</Link> to convert between them.</>
              ) : null)}{" "}
            Ranges are 90% two-sided (the 5th to 95th percentile).
          </ResultSummary>
          {(d.states || []).length > 0 && (
            <ul className="fc-states" aria-label="What's missing">
              {d.states.map((s, i) => (
                <li key={i} className={`fc-state fc-${s.kind}`}><span className="fc-state-icon" aria-hidden="true">!</span>{s.text}</li>
              ))}
            </ul>
          )}
          <Bars d={d} />
          <div className="maint-scroll fc-scroll">
            <table className="lib-table fc-table fcd-table">
              <caption className="sr-only">The forecast by {d.basis === "hours" ? "running hours" : d.period}</caption>
              <thead>
                <tr>
                  <th scope="col">{d.basis === "hours" ? "Running hours" : GROUP_WORD[d.period] || "Period"}</th>
                  {cols.map((c) => <th key={c.id} scope="col" className="num" title={c.title}>{c.label}</th>)}
                </tr>
              </thead>
              <tbody>
                {d.rows.map((r, i) => (
                  <tr key={d.basis === "hours" ? r.from_hours : r.start}>
                    <th scope="row" title={d.basis === "hours" ? meterText(r) : `${dayText(r.start)} to ${dayText(r.end)}`}>{rowLabel(d, r, i)}</th>
                    {cols.map((c) => <td key={c.id} className="num">{c.cell(r)}</td>)}
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr>
                  <th scope="row">In all</th>
                  {cols.map((c) => <td key={c.id} className="num">{c.cell(d.totals)}</td>)}
                </tr>
              </tfoot>
            </table>
          </div>
          {emptyColumns(d).length > 0 && d.rows.some((r) => r.tasks) && (
            <p className="lib-date">No {emptyColumns(d).join(", ")} in this forecast: set them in each task&apos;s What it needs (labour, spares and consumables, at the trade rates) or a package&apos;s visit cost.</p>
          )}
          {d.totals?.probability != null && <p className="lib-date">{formatChance(d.totals.probability)} chance of at least one failure in {horizonText(d)}.</p>}
          <WhenNext d={d} />
          {left.length > 0 && (
            <ResultDetails summary={`Not placed (${left.length})`} open={left.length <= 4}>
              <ul className="td-rows fc-list">
                {left.map((x) => (x.life ? (
                  <li key={`m-${x.link_id}-${x.position.id}`}><strong>{x.position.name}</strong>: {x.name}<div className="lib-date">Failures not forecast: {x.reason}.</div></li>
                ) : (
                  <li key={`t-${x.task.id}`}><strong>{x.task.name}</strong> <span className="lib-date">· {x.position.name}</span>
                    <div className="lib-date">{x.reason}{x.link ? <> · <Link to={x.link}>Set a duty</Link></> : null}</div></li>
                )))}
              </ul>
            </ResultDetails>
          )}
          {groups.length > 0 && (
            <ResultDetails summary={`What to enter (${groups.reduce((t, g) => t + g.items.length, 0)})`} open>
              {groups.map((g) => (
                <section key={g.id} className="fc-enter-group" aria-label={g.title}>
                  <h3 className="fc-enter-title">{g.title}</h3>
                  <p className="lib-date">{g.lead}</p>
                  <ul className="td-rows fc-list">
                    {g.items.map((x) => (
                      <li key={x.key}>
                        <strong>{x.name}</strong> <span className="lib-date">· {x.where}</span>
                        {x.link && <> · <Link to={x.link}>{x.action}</Link></>}
                        <div className="lib-date">{x.why}</div>
                      </li>
                    ))}
                  </ul>
                </section>
              ))}
            </ResultDetails>
          )}
          <ResultDetails summary={`Failures: the life models used (${(d.models || []).length})`}>
            {!(d.models || []).length && <p className="lib-date">No life model counted here. Attach one in {tabPlace("models")}{subject.kind !== "level" ? ", on a failure mode this task serves" : ""}.</p>}
            <ul className="td-rows fc-list">
              {(d.models || []).map((m) => (
                <li key={`${m.link_id}-${m.position.id}`}>
                  <strong>{m.position.name}</strong>: {m.name}
                  {m.placeholder && <span className="fc-flag-word"> · placeholder</span>}
                  <div>{failuresText(m.expected_failures, m.failures_range)} failures expected
                    {m.expected_cost != null ? `, ${costRangeText(m.expected_cost, m.cost_range)}` : ""}
                    {m.probability != null ? ` · ${formatChance(m.probability)} chance of at least one` : ""}
                  </div>
                  <div className="lib-date">{m.rests_on}</div>
                </li>
              ))}
            </ul>
          </ResultDetails>
          {(d.by_position || []).length > 1 && (
            <ResultDetails summary={`By position (${d.by_position.length})`}>
              <div className="maint-scroll">
                <table className="lib-table fc-table">
                  <thead>
                    <tr><th scope="col">Position</th><th scope="col" className="num">Times done</th><th scope="col" className="num">Labour</th>
                      <th scope="col" className="num">Planned cost</th><th scope="col" className="num">Expected failures</th><th scope="col" className="num">Failure cost</th></tr>
                  </thead>
                  <tbody>
                    {d.by_position.map((p) => (
                      <tr key={p.position.id}>
                        <th scope="row" style={{ "--fc-depth": p.depth }} className="fc-depth" title={p.hours_basis || undefined}>{p.position.name}</th>
                        <td className="num">{p.tasks}</td>
                        <td className="num">{p.labour_hours ? hoursText(p.labour_hours) : "—"}</td>
                        <td className="num">{p.planned_cost ? moneyText(p.planned_cost) : "—"}</td>
                        <td className="num">{p.failures ? sig(p.failures, 2) : "—"}</td>
                        <td className="num">{p.failure_cost ? moneyText(p.failure_cost) : "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </ResultDetails>
          )}
          {(d.notes || []).length > 0 && <ul className="lib-date fc-notes">{d.notes.map((n, i) => <li key={i}>{n}</li>)}</ul>}
        </div>
      )}
    </section>
  );
}

const GROUP_WORD = { day: "Day", week: "Week", month: "Month", quarter: "Quarter", year: "Year" };
