import { useEffect, useMemo, useRef, useState } from "react";
import { endOperatingPlan, getOperatingPlan, setOperatingPlan } from "../api.js";
import { saveErrorText } from "../confirm.js";
import { formatDate } from "../dates.js";
import {
  PLAN_KINDS, RATE_PER, WEEKDAYS, formFromPlan, hoursByDay, hoursShort, hoursWords, parseRuns, planFromForm, planWords,
  typicalWeek,
} from "../operatingPlan.js";
import { today as workspaceToday } from "./MaintenanceParts.jsx";
import { useConfirm } from "./ConfirmProvider.jsx";
import TablePane from "./TablePane.jsx";
import "./OperatingPlanPane.css";

// A position's operating plan, in the Explorer's table area beside the tree (?plan=<position id>,
// from the Measurements tab's row menu and the Summary's "Operating plan" line; no modal): how it
// runs. A background (a repeating week, a roster, a rate, runs only, or all the time) with set
// runs on top if wanted (typed, pasted or imported from a spreadsheet: on, off). It shows at once
// "about 80 hours a week" and a strip of the next two weeks. A position with no plan of its own
// runs to the nearest above it inside the asset opened ("From Pump station 1"), with "Give this its
// own plan". Saved as events (operating_plan.set / ended): a new plan from a date ends the one
// before it there; nothing earlier is rewritten. Once saved, its hours (the strip, hours a week) are
// RePyability's, in the plan's time zone; with an hours counter here, plan against actual over the
// last 90 days offers a utilisation, saved only on "Use 82%".
//
//   position {id, name}   root: the asset opened (?root=), so a plan above it is never used
//   phone, headingRef, onClose, onDirty: TablePane's      onChanged(text): saved or ended

const STRIP_DAYS = 14;

function Strip({ days }) {
  return (
    <ol className="op-strip" aria-label="The next two weeks">
      {days.map((d) => (
        <li key={d.date} className="op-day">
          <span className="op-day-name">{formatDate(d.date, { weekday: true, year: false })}</span>
          <span className="op-bar" role="img" aria-label={`${hoursShort(d.hours)} on ${formatDate(d.date, { weekday: true })}`}>
            {d.runs.map((r, i) => (
              <span key={i} className={`op-run op-l-${r.layer}`} style={{ left: `${(r.from / 24) * 100}%`, width: `${((r.to - r.from) / 24) * 100}%` }} />
            ))}
            {d.spread > 0 && <span className="op-spread" style={{ width: `${Math.min(100, (d.spread / 24) * 100)}%` }} />}
          </span>
          <span className="op-day-hours">{hoursShort(d.hours)}</span>
        </li>
      ))}
    </ol>
  );
}

function RunsBox({ label, hint, value, onChange, disabled }) {
  const file = useRef(null);
  const parsed = useMemo(() => parseRuns(value), [value]);
  const read = (e) => {
    const f = e.target.files?.[0];
    if (!f) return;
    f.text().then((text) => onChange(value.trim() ? `${value.trim()}\n${text}` : text));
    e.target.value = "";
  };
  return (
    <div className="op-runs">
      <label className="op-label" htmlFor="op-runs-text">{label}</label>
      <p className="lib-date op-hint">{hint}</p>
      <textarea id="op-runs-text" rows={5} value={value} disabled={disabled} spellCheck={false}
                placeholder={"2026-11-14 12:31, 2026-11-15 03:27\n2026-11-15 12:30, 2026-11-16 03:30"}
                onChange={(e) => onChange(e.target.value)} />
      <div className="op-runs-foot">
        <button type="button" className="link" onClick={() => file.current?.click()} disabled={disabled}>Import a CSV…</button>
        <input ref={file} type="file" accept=".csv,.txt,text/csv,text/plain" hidden onChange={read} />
        <span className="lib-date">{parsed.runs.length ? `${parsed.runs.length} run${parsed.runs.length === 1 ? "" : "s"}` : ""}</span>
      </div>
    </div>
  );
}

function KindForm({ form, set, disabled }) {
  if (form.kind === "continuous") return <p className="lib-date">It runs around the clock, every day.</p>;
  if (form.kind === "rate") {
    return (
      <div className="op-row">
        <span>About</span>
        <input className="op-num" type="number" min="0" step="any" inputMode="decimal" value={form.rate.amount} disabled={disabled}
               aria-label="Hours" onChange={(e) => set({ rate: { ...form.rate, amount: e.target.value } })} />
        <span>hours a</span>
        <select value={form.rate.per} disabled={disabled} aria-label="Per"
                onChange={(e) => set({ rate: { ...form.rate, per: e.target.value } })}>
          {Object.keys(RATE_PER).map((p) => <option key={p} value={p}>{p}</option>)}
        </select>
      </div>
    );
  }
  if (form.kind === "roster") {
    const r = form.roster;
    const put = (k) => (e) => set({ roster: { ...r, [k]: e.target.value } });
    return (
      <div className="op-col">
        <div className="op-row">
          <input className="op-num" type="number" min="1" step="1" inputMode="numeric" value={r.on} onChange={put("on")} disabled={disabled} aria-label="Days on" />
          <span>days on,</span>
          <input className="op-num" type="number" min="0" step="1" inputMode="numeric" value={r.off} onChange={put("off")} disabled={disabled} aria-label="Days off" />
          <span>days off</span>
        </div>
        <div className="op-row">
          <span>from</span>
          <input type="time" value={r.start} onChange={put("start")} disabled={disabled} aria-label="Start" />
          <span>to</span>
          <input type="time" value={r.stop} onChange={put("stop")} disabled={disabled} aria-label="Stop" />
        </div>
        <label className="op-row">First day on <input type="date" value={r.anchor} onChange={put("anchor")} disabled={disabled} /></label>
      </div>
    );
  }
  if (form.kind === "runs") {
    return <RunsBox label="Runs" hint="One run a line: when it goes on, then off. Paste from a spreadsheet (two columns) or import a CSV. It's off between them."
                    value={form.runs} onChange={(v) => set({ runs: v })} disabled={disabled} />;
  }
  const shifts = form.shifts;
  const put = (i, patch) => set({ shifts: shifts.map((s, j) => (j === i ? { ...s, ...patch } : s)) });
  return (
    <div className="op-col">
      {shifts.map((s, i) => (
        <fieldset key={i} className="op-shift">
          <legend className="sr-only">Shift {i + 1}</legend>
          <div className="op-days" role="group" aria-label={`Shift ${i + 1}: days`}>
            {WEEKDAYS.map((d) => (
              <label key={d} className={"op-daybox" + (s.days.includes(d) ? " on" : "")}>
                <input type="checkbox" checked={s.days.includes(d)} disabled={disabled}
                       onChange={(e) => put(i, { days: e.target.checked ? [...s.days, d] : s.days.filter((x) => x !== d) })} />
                {d.slice(0, 3)}
              </label>
            ))}
          </div>
          <div className="op-row">
            <input type="time" value={s.start} onChange={(e) => put(i, { start: e.target.value })} disabled={disabled} aria-label={`Shift ${i + 1}: start`} />
            <span>to</span>
            <input type="time" value={s.stop} onChange={(e) => put(i, { stop: e.target.value })} disabled={disabled} aria-label={`Shift ${i + 1}: stop`} />
            {shifts.length > 1 && (
              <button type="button" className="link" disabled={disabled} onClick={() => set({ shifts: shifts.filter((_, j) => j !== i) })}>Remove</button>
            )}
          </div>
        </fieldset>
      ))}
      <button type="button" className="link op-add" disabled={disabled}
              onClick={() => set({ shifts: [...shifts, { days: ["Saturday"], start: "08:00", stop: "12:00" }] })}>+ Add a shift</button>
      <p className="lib-date">A stop before its start is the next morning (22:00 to 06:00).</p>
    </div>
  );
}

const STATUS = { current: "Running now", planned: "From", ended: "Ended" };

export default function OperatingPlanPane({ position, root = null, phone = false, headingRef = null, onClose, onDirty, onChanged,
  readOnly = null }) {
  const confirm = useConfirm();
  const today = workspaceToday();
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [form, setForm] = useState(null);
  const [saving, setSaving] = useState(false);
  const [failed, setFailed] = useState(null);
  const [n, setN] = useState(0);

  useEffect(() => {
    let live = true;
    getOperatingPlan("position", position.id, root).then((d) => {
      if (!live) return;
      setData(d);
      // No plan here or above: the form is open, so the first plan is a few clicks away.
      if (!d.plan && !readOnly) setForm((f) => f || formFromPlan(null, d.today || today));
    }, (e) => live && setError(e));
    return () => { live = false; };
  }, [position.id, root, n]); // eslint-disable-line react-hooks/exhaustive-deps

  const edit = (f) => { setForm(f); setFailed(null); onDirty?.(!!f); };
  const set = (patch) => edit({ ...form, ...patch });
  const built = form ? planFromForm(form) : null;
  const preview = built?.plan || null;
  const days = useMemo(() => (preview ? hoursByDay(preview, data?.today || today, STRIP_DAYS) : null), [preview, data?.today]); // eslint-disable-line react-hooks/exhaustive-deps
  const week = preview ? typicalWeek(preview) : null;
  const total = days ? days.reduce((t, d) => t + d.hours, 0) : 0;

  const save = async () => {
    if (!preview) return;
    setSaving(true);
    setFailed(null);
    try {
      await setOperatingPlan(position.id, { plan: preview, name: form.name.trim(), from: form.from || null });
      edit(null);
      setN((x) => x + 1);
      onChanged?.(`Saved how ${position.name} runs: ${planWords(preview)}.`);
    } catch (e) {
      setFailed(saveErrorText(e, { offline: navigator.onLine === false }));
    } finally {
      setSaving(false);
    }
  };
  // Plan against actual's proposal, saved only when asked: the same plan with that utilisation.
  const applyUtilisation = async (utilisation) => {
    setSaving(true);
    setFailed(null);
    try {
      await setOperatingPlan(position.id, { plan: { ...data.plan.plan, utilisation }, name: data.plan.name || "" });
      setN((x) => x + 1);
      onChanged?.(`${position.name}'s plan now counts ${Math.round(utilisation * 100)}% of its planned hours.`);
    } catch (e) {
      setFailed(saveErrorText(e, { offline: navigator.onLine === false }));
    } finally {
      setSaving(false);
    }
  };
  const end = async () => {
    const ok = await confirm({
      title: "End this plan?", body: `${position.name} stops running to it from today, and runs to the plan above it (if any) again. It stays in the history.`,
      confirmLabel: "End the plan", pendingLabel: "Ending…", failedWhat: "end it",
      run: () => endOperatingPlan(position.id).then(() => true),
    });
    if (ok) { setN((x) => x + 1); onChanged?.(`Ended ${position.name}'s own operating plan.`); }
  };

  const plan = data?.plan;
  const own = plan && !data.inherited_from;
  return (
    <TablePane title="Operating plan" subject={position.name} phone={phone} busy={saving} headingRef={headingRef} onClose={onClose}
               className="op-pane">
      <div className="op-body">
        {error && <div className="card error">Couldn&apos;t load the operating plan: {error.message}</div>}
        {!data && !error && <p className="lib-date">Loading…</p>}
        {data && !form && (
          <section className="op-now" aria-label="How it runs now">
            {plan ? (
              <>
                <p className="op-answer">
                  <strong>{planWords(plan.plan)}</strong>
                  {plan.hours_per_week != null && <> · {hoursWords(plan.hours_per_week)}</>}
                </p>
                {data.inherited_from ? (
                  <p className="lib-date">From {data.inherited_from.name}: it has no plan of its own, so it runs as that does.</p>
                ) : (
                  <p className="lib-date">Its own plan, since {formatDate(plan.from)}{plan.name ? ` (${plan.name})` : ""}. Times are {plan.time_zone || "the site's"} clock times.</p>
                )}
                {data.days?.length > 0 && (
                  <>
                    <h3 className="op-sub">The next two weeks · {hoursShort(data.days.reduce((t, d) => t + d.hours, 0))}</h3>
                    <Strip days={data.days} />
                    <p className="lib-date">Real hours in {plan.time_zone || "the site's"} time{data.hours_basis ? `: ${data.hours_basis}` : ""}. Usage tasks go on dates from these hours.</p>
                  </>
                )}
                {data.against_actual && (
                  <section className="op-actual" aria-label="Plan against actual">
                    <h3 className="op-sub">Plan against actual</h3>
                    <p>{data.against_actual.text}</p>
                    {data.against_actual.proposal && (
                      own && !readOnly ? (
                        <p className="op-row op-wrap">
                          <span className="lib-date">{data.against_actual.proposal.text}</span>
                          <button type="button" className="secondary sm" disabled={saving} onClick={() => applyUtilisation(data.against_actual.proposal.utilisation)}>
                            Use {Math.round(data.against_actual.proposal.utilisation * 100)}%
                          </button>
                        </p>
                      ) : (
                        <p className="lib-date">The plan is {data.inherited_from ? `${data.inherited_from.name}'s` : "not its own"}: give this its own plan to set how much of it runs here.</p>
                      )
                    )}
                  </section>
                )}
                {failed && <p className="field-error" role="alert">{failed}</p>}
                {!readOnly && (
                  <div className="op-actions">
                    <button type="button" className="secondary" onClick={() => edit({ ...formFromPlan(plan, data.today || today), name: own ? plan.name : "" })}>
                      {own ? "Change it" : "Give this its own plan"}
                    </button>
                    {own && <button type="button" className="link td-danger" onClick={end}>End this plan…</button>}
                  </div>
                )}
              </>
            ) : (
              <p className="lib-date">No operating plan here or above it.</p>
            )}
          </section>
        )}
        {form && (
          <form className="op-form" onSubmit={(e) => { e.preventDefault(); save(); }}>
            {!plan && <p className="op-answer">Say how {position.name} runs. Usage tasks (every 2,000 operating hours) will go on dates from it.</p>}
            {plan && data.inherited_from && <p className="lib-date">Starting from {data.inherited_from.name}&apos;s plan: change what differs here.</p>}
            <fieldset className="op-kinds">
              <legend className="op-label">It runs</legend>
              <div className="op-kind-list" role="radiogroup">
                {PLAN_KINDS.map(([k, label, hint]) => (
                  <label key={k} className={"op-kind" + (form.kind === k ? " on" : "")} title={hint}>
                    <input type="radio" name="op-kind" value={k} checked={form.kind === k} onChange={() => set({ kind: k })} disabled={saving} />
                    {label}
                  </label>
                ))}
              </div>
              <p className="lib-date op-hint">{PLAN_KINDS.find(([k]) => k === form.kind)?.[2]}</p>
            </fieldset>
            <KindForm form={form} set={set} disabled={saving} />
            {form.kind !== "runs" && (
              <details className="op-specific" open={!!form.specific.trim()}>
                <summary>Set runs first (optional)</summary>
                <RunsBox label="Runs you know about" value={form.specific} onChange={(v) => set({ specific: v })} disabled={saving}
                         hint="Today's and tomorrow's runs, say. From the start of the first run's day to the end of the last, they're all the running there is; then the plan you picked above takes over, with no gap." />
              </details>
            )}
            <div className="op-row op-meta">
              <label className="op-row">From <input type="date" value={form.from} min={own ? plan.from : undefined} onChange={(e) => set({ from: e.target.value })} disabled={saving} /></label>
              <label className="op-row op-grow">Name (optional) <input value={form.name} maxLength={200} placeholder="e.g. Day shifts" onChange={(e) => set({ name: e.target.value })} disabled={saving} /></label>
            </div>
            {built?.problem ? <p className="field-error" role="alert">{built.problem}</p> : (
              <section className="op-preview" aria-live="polite" aria-label="What it comes to">
                <p className="op-answer">
                  <strong>{week != null ? hoursWords(week)[0].toUpperCase() + hoursWords(week).slice(1) : "Runs only when listed"}</strong>
                  {" · "}{hoursShort(total)} in the next two weeks
                </p>
                <Strip days={days} />
                <p className="lib-date op-legend">
                  <span className="op-key op-specific-key" aria-hidden="true" /> set runs
                  <span className="op-key op-background-key" aria-hidden="true" /> the plan
                  {form.kind === "rate" && <><span className="op-key op-spread-key" aria-hidden="true" /> a rate, spread over the day</>}
                  {" "}· A quick preview in clock hours; once saved, the hours are worked out in the site&apos;s time zone (daylight saving counted).
                </p>
              </section>
            )}
            {failed && <p className="field-error" role="alert">{failed}</p>}
            <div className="op-actions">
              <button type="submit" disabled={saving || !!built?.problem}>{saving ? "Saving…" : "Save"}</button>
              {plan && <button type="button" className="secondary" onClick={() => edit(null)} disabled={saving}>Cancel</button>}
            </div>
          </form>
        )}
        {data?.own?.length > 0 && !form && (
          <section className="op-history" aria-label="Its plans">
            <h3 className="op-sub">Its own plans</h3>
            <ul className="td-rows">
              {[...data.own].reverse().map((p) => (
                <li key={p.id} className="op-hist-row">
                  <span>{planWords(p.plan)}</span>
                  <span className="lib-date">
                    {p.status === "planned" ? `From ${formatDate(p.from)}` : `${formatDate(p.from)} to ${p.until ? formatDate(p.until) : "now"}`}
                    {p.status === "current" ? ` · ${STATUS.current}` : ""}
                  </span>
                </li>
              ))}
            </ul>
          </section>
        )}
      </div>
    </TablePane>
  );
}
