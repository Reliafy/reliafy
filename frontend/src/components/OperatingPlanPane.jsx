import { useEffect, useMemo, useRef, useState } from "react";
import { endOperatingPlan, getOperatingPlan, setOperatingPlan } from "../api.js";
import { saveErrorText } from "../confirm.js";
import { formatDate } from "../dates.js";
import {
  PLAN_KINDS, RATE_PER, WEEKDAYS, formFromPlan, hoursByDay, hoursShort, hoursWords, overnightTimes, parseRuns, planFromForm, planWords,
  typicalWeek,
} from "../operatingPlan.js";
import { today as workspaceToday } from "./MaintenanceParts.jsx";
import { useConfirm } from "./ConfirmProvider.jsx";
import TablePane from "./TablePane.jsx";
import ChoiceChips from "./ui/ChoiceChips.jsx";
import { Checkbox, Select, TextArea, TextInput } from "./ui/Controls.jsx";
import { DateInput, TimeInput } from "./ui/DateTimeInput.jsx";
import { ReadsAs } from "./ui/InputGroup.jsx";
import { ResultDetails } from "./ui/ResultSummary.jsx";
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
      <TextArea id="op-runs-text" rows={4} value={value} disabled={disabled} spellCheck={false} className="op-runs-text"
                placeholder={"For example:\n2026-11-14 12:31, 2026-11-15 03:27\n2026-11-15 12:30, 2026-11-16 03:30"}
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
        <TextInput className="op-num" type="number" min="0" step="any" inputMode="decimal" value={form.rate.amount} disabled={disabled}
                   aria-label="Hours" onChange={(e) => set({ rate: { ...form.rate, amount: e.target.value } })} />
        <span>hours a</span>
        <Select className="op-per" value={form.rate.per} disabled={disabled} aria-label="Per"
                onChange={(e) => set({ rate: { ...form.rate, per: e.target.value } })}>
          {Object.keys(RATE_PER).map((p) => <option key={p} value={p}>{p}</option>)}
        </Select>
      </div>
    );
  }
  if (form.kind === "roster") {
    const r = form.roster;
    const put = (k) => (e) => set({ roster: { ...r, [k]: e.target.value } });
    return (
      <div className="op-col">
        <div className="op-row">
          <TextInput className="op-num" type="number" min="1" step="1" inputMode="numeric" value={r.on} onChange={put("on")} disabled={disabled} aria-label="Days on" />
          <span>days on,</span>
          <TextInput className="op-num" type="number" min="0" step="1" inputMode="numeric" value={r.off} onChange={put("off")} disabled={disabled} aria-label="Days off" />
          <span>days off,</span>
          <span>from</span>
          <TimeInput value={r.start} onChange={put("start")} disabled={disabled} aria-label="Start" />
          <span>to</span>
          <TimeInput value={r.stop} onChange={put("stop")} disabled={disabled} aria-label="Stop" />
        </div>
        <div className="op-row">
          <label htmlFor="op-anchor">First day on</label>
          <DateInput id="op-anchor" value={r.anchor} onChange={put("anchor")} disabled={disabled} />
        </div>
        <Overnight form={form} />
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
              <Checkbox key={d} className={"op-daybox" + (s.days.includes(d) ? " on" : "")} checked={s.days.includes(d)} disabled={disabled}
                        onChange={(e) => put(i, { days: e.target.checked ? [...s.days, d] : s.days.filter((x) => x !== d) })}
                        label={d.slice(0, 3)} />
            ))}
          </div>
          <div className="op-row">
            <TimeInput value={s.start} onChange={(e) => put(i, { start: e.target.value })} disabled={disabled} aria-label={`Shift ${i + 1}: start`} />
            <span>to</span>
            <TimeInput value={s.stop} onChange={(e) => put(i, { stop: e.target.value })} disabled={disabled} aria-label={`Shift ${i + 1}: stop`} />
            {shifts.length > 1 && (
              <button type="button" className="link" disabled={disabled} onClick={() => set({ shifts: shifts.filter((_, j) => j !== i) })}>Remove</button>
            )}
          </div>
        </fieldset>
      ))}
      <button type="button" className="link op-add" disabled={disabled}
              onClick={() => set({ shifts: [...shifts, { days: ["Saturday"], start: "08:00", stop: "12:00" }] })}>+ Add a shift</button>
      <Overnight form={form} />
    </div>
  );
}

// A stop before its start ends the next morning: said with the times entered, only when one does.
function Overnight({ form }) {
  const times = overnightTimes(form);
  if (!times.length) return <p className="lib-date op-hint">A stop time before the start time ends the next morning.</p>;
  return (
    <p className="lib-date op-hint">
      {times.map(([a, b]) => `${a} to ${b}`).join(" and ")} {times.length === 1 ? "runs" : "run"} past midnight, ending the next morning.
    </p>
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
            <div className="op-inputs">
              {!plan && <p className="op-answer op-text">Say how {position.name} runs. Tasks that fall due by operating hours go on dates from it.</p>}
              {plan && data.inherited_from && <p className="lib-date op-text">Starting from {data.inherited_from.name}&apos;s plan: change what differs here.</p>}
              <div className="op-kinds" role="group" aria-labelledby="op-kinds-label">
                <span className="op-label" id="op-kinds-label">It runs</span>
                <ChoiceChips label="It runs" value={form.kind} disabled={saving} className="op-kind-list"
                             options={PLAN_KINDS.map(([value, label, title]) => ({ value, label, title }))}
                             onChange={(k) => k && set({ kind: k })} />
                <p className="lib-date op-hint">{PLAN_KINDS.find(([k]) => k === form.kind)?.[2]}.</p>
              </div>
              <KindForm form={form} set={set} disabled={saving} />
              <div className="op-kinds op-use" role="group" aria-labelledby="op-use-label">
                <span className="op-label" id="op-use-label">Other use <span className="field-opt">optional</span></span>
                <p className="lib-date op-hint op-text">Distance or counts it does in a day, week, month or year, so a model in km or cycles can be read against dates.</p>
                <div className="op-row">
                  <span>About</span>
                  <TextInput className="op-num" type="number" min="0" step="any" inputMode="decimal" value={form.use.amount}
                             disabled={saving} aria-label="How much" placeholder="e.g. 400"
                             onChange={(e) => set({ use: { ...form.use, amount: e.target.value } })} />
                  <TextInput className="op-unit" value={form.use.meter} maxLength={24} disabled={saving}
                             aria-label="Unit, such as km or cycles" placeholder="unit, e.g. km"
                             onChange={(e) => set({ use: { ...form.use, meter: e.target.value } })} />
                  <span>a</span>
                  <Select className="op-per" value={form.use.per} disabled={saving} aria-label="Per"
                          onChange={(e) => set({ use: { ...form.use, per: e.target.value } })}>
                    {Object.keys(RATE_PER).map((p) => <option key={p} value={p}>{p}</option>)}
                  </Select>
                </div>
              </div>
              {form.kind !== "runs" && (
                <ResultDetails summary="Set runs first (optional)" open={!!form.specific.trim()}>
                  <RunsBox label="Runs you know about" value={form.specific} onChange={(v) => set({ specific: v })} disabled={saving}
                           hint="Today's and tomorrow's runs, say. From the start of the first run's day to the end of the last, they're all the running there is; then the plan you picked above takes over, with no gap." />
                </ResultDetails>
              )}
              <div className="op-row op-meta">
                <label htmlFor="op-from">From</label>
                <DateInput id="op-from" value={form.from} min={own ? plan.from : undefined} onChange={(e) => set({ from: e.target.value })} disabled={saving} />
                <label htmlFor="op-name">Name <span className="field-opt">optional</span></label>
                <TextInput id="op-name" className="op-name" value={form.name} maxLength={200} placeholder="e.g. Day shifts" onChange={(e) => set({ name: e.target.value })} disabled={saving} />
              </div>
            </div>
            {built?.problem ? <p className="field-error op-result" role="alert">{built.problem}</p> : (
              <section className="op-preview op-result" aria-live="polite" aria-label="What it comes to">
                <ReadsAs>{planWords(preview)}</ReadsAs>
                <p className="op-answer">
                  <strong>{week != null ? hoursWords(week)[0].toUpperCase() + hoursWords(week).slice(1) : "Runs only when listed"}</strong>
                  {" · "}{hoursShort(total)} in the next two weeks
                </p>
                <Strip days={days} />
                <p className="lib-date op-legend">
                  <span className="op-key op-specific-key" aria-hidden="true" /> set runs
                  <span className="op-key op-background-key" aria-hidden="true" /> the plan
                  {form.kind === "rate" && <><span className="op-key op-spread-key" aria-hidden="true" /> a rate, spread over the day</>}
                </p>
                <p className="lib-date op-text">A quick preview in clock hours; once saved, the hours are worked out in the site&apos;s time zone (daylight saving counted).</p>
              </section>
            )}
            <div className="op-actions">
              {failed && <p className="field-error" role="alert">{failed}</p>}
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
