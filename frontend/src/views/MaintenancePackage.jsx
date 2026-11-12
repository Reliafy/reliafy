import { Fragment, useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { changePackage, getPackage, raisePackageVisit, updatePackage } from "../api.js";
import PageHeader from "../components/ui/PageHeader.jsx";
import LoadFailed from "../components/LoadFailed.jsx";
import TablePane from "../components/TablePane.jsx";
import Chip from "../components/ui/Chip.jsx";
import { PageTitle } from "../components/usePageTitle.js";
import { RowLink, rowOpen } from "../components/LibRows.jsx";
import { DueChip, Field, fmtDate, today as workspaceToday } from "../components/MaintenanceParts.jsx";
import { PauseDialog, RetireDialog, StatusChips } from "../components/LsaPanel.jsx";
import { SubjectCell } from "./MaintenanceHome.jsx";
import usePhone from "../usePhone.js";
import { WEEKDAYS, dayName, rollupLines, visitRuleText } from "../lsaTab.js";
import { PACKAGES_PATH, linesText, packagePath, workOrderPath } from "../maintenanceOrders.js";
import {
  NTHS, PACKAGE_UNITS, editBody, formProblem, initialForm, outcomeText, packageSentence, patternsFor, taskLabel, visitDay,
  visitTasksText,
} from "../packagePage.js";
import { ORDERS_PATH, PACKAGES_LABEL } from "../navigation.js";
import { subjectPath } from "../maintenanceSubjects.js";
import "./Maintenance.css";

const plural = (n, one, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;
const unitWord = (n, unit) => (Number(n) === 1 ? String(unit).replace(/s$/, "") : unit);

// One work package (Maintenance › Packages › one): how it stands in one sentence,
// its details and layers, the next six visits, its tasks with their visit rules,
// and its recent work orders with what came of each. Edit opens beside the page
// (a pane, not a dialog); Pause, Resume, Retire and Restore are in its ⋯.
export default function MaintenancePackage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const phone = usePhone();
  const [pkg, setPkg] = useState(null);
  const [error, setError] = useState(null);
  const [editing, setEditing] = useState(false);
  const [modal, setModal] = useState(null); // "pause" | "retire"
  const [said, setSaid] = useState(null);
  const today = workspaceToday();

  useEffect(() => {
    let live = true;
    setPkg(null);
    setError(null);
    setEditing(false);
    getPackage(id).then((p) => live && setPkg(p)).catch((e) => live && setError(e.message));
    return () => { live = false; };
  }, [id]);

  if (error && !pkg) {
    return <div className="app"><LoadFailed header error={error} notFound="Package not found." to={PACKAGES_PATH} label="Back to Packages" /></div>;
  }
  if (!pkg) return <div className="app"><div className="card empty">Loading…</div></div>;

  const changed = (fresh, text) => {
    setModal(null);
    if (fresh?.id === pkg.id) setPkg(fresh);
    setSaid(text || null);
  };
  const run = async (change, text) => {
    try {
      changed(await changePackage(pkg.id, change), text);
    } catch (e) {
      setSaid(e.message);
    }
  };
  const live = pkg.status !== "retired";
  const backFromPause = pkg.flags?.includes("past_return_date");
  const menu = (
    <>
      {pkg.status === "active" && !backFromPause && <button className="ovm-item" onClick={() => setModal("pause")}>Pause…</button>}
      {(pkg.status === "paused" || backFromPause) && <button className="ovm-item" onClick={() => run("resume", "Resumed.")}>Resume</button>}
      {live && (
        <button className="ovm-item danger" onClick={() => setModal("retire")} disabled={!!pkg.open_work_order}
                title={pkg.open_work_order ? `Close or cancel work order #${pkg.open_work_order.number} first` : undefined}>
          Retire…
        </button>
      )}
      {!live && <button className="ovm-item" onClick={() => run("restore", "Restored.")}>Restore</button>}
    </>
  );

  return (
    <div className="app">
      <PageTitle name={pkg.name} />
      <PageHeader
        crumbs={[{ label: "Maintenance", to: ORDERS_PATH }, { label: PACKAGES_LABEL, to: PACKAGES_PATH }]}
        title={pkg.name}
        badges={<StatusChips pkg={pkg} today={today} />}
        meta={[pkg.subject && `on ${pkg.subject.name}`, pkg.trade && `needs: ${pkg.trade}`, `${plural(pkg.tasks?.length || 0, "task")}`]
          .filter(Boolean).join(" · ")}
        primary={live ? <button onClick={() => setEditing(true)} aria-expanded={editing}>Edit</button> : null}
        menu={menu}
        id={pkg.id}
      />
      <p className="maint-answer">{packageSentence(pkg, today)}</p>
      {said && <p className="lib-date" role="status">{said}</p>}

      <div className={"pkg-page" + (editing && !phone ? " is-editing" : "")}>
        <div className="pkg-main">
          <Details pkg={pkg} />
          <NextVisits pkg={pkg} today={today} onRaise={async () => {
            try {
              const out = await raisePackageVisit(pkg.id);
              setPkg(await getPackage(pkg.id));
              setSaid(`${out.raised ? "Raised" : "Already open:"} work order #${out.work_order.number} for this visit.`);
            } catch (e) {
              setSaid(e.message);
            }
          }} />
          <Tasks pkg={pkg} />
          <WorkOrders pkg={pkg} navigate={navigate} />
        </div>
        {editing && (
          <EditPane pkg={pkg} phone={phone} onClose={() => setEditing(false)}
                    onSaved={(fresh) => { setPkg(fresh); setEditing(false); setSaid("Saved."); }} />
        )}
      </div>

      {modal === "pause" && <PauseDialog pkg={pkg} onClose={() => setModal(null)} onDone={changed} />}
      {modal === "retire" && <RetireDialog pkg={pkg} onClose={() => setModal(null)} onDone={changed} />}
    </div>
  );
}

function Details({ pkg }) {
  const wo = pkg.open_work_order;
  // What a visit needs (its tasks' LSA added up), in the same rows as the details.
  const needs = rollupLines(pkg.rollup);
  return (
    <section className="card">
      <dl className="maint-dl">
        {pkg.subject && <><dt>On</dt><dd><Link to={subjectPath(pkg.subject)}>{pkg.subject.name}</Link></dd></>}
        <dt>Timing</dt><dd>{pkg.cadence?.text}{pkg.timing === "from_last_visit" ? "" : " (set dates)"}</dd>
        {pkg.tolerance?.amount ? <><dt>On time within</dt><dd>{pkg.tolerance.amount} {unitWord(pkg.tolerance.amount, pkg.tolerance.unit)} after the visit date</dd></> : null}
        {pkg.season?.text && <><dt>Season</dt><dd>{pkg.season.text}</dd></>}
        {pkg.trade && <><dt>Trade</dt><dd>{pkg.trade}</dd></>}
        {pkg.shutdown && (
          <><dt>Shutdown</dt><dd>
            {pkg.shutdown.words[0].toUpperCase() + pkg.shutdown.words.slice(1)}
            {pkg.shutdown.scope ? ` · takes down ${pkg.shutdown.scope.map((x) => x.name).join(", ")}` : pkg.subject ? ` · takes down all of ${pkg.subject.name}` : ""}
            {pkg.shutdown.dates ? ` · on ${pkg.shutdown.dates.join(", ")}` : ""}
          </dd></>
        )}
        {wo && (
          <><dt>Open visit</dt><dd>
            <Link to={workOrderPath(wo.id)}>#{wo.number}</Link> for {fmtDate(wo.visit_on)}
            {wo.late && <> <Chip tone="danger">late</Chip></>}
          </dd></>
        )}
        {pkg.pause?.text && <><dt>Paused</dt><dd>{pkg.pause.text}{pkg.pause.reason ? `: ${pkg.pause.reason}` : ""}</dd></>}
        {pkg.notes && <><dt>Notes</dt><dd className="pkg-notes">{pkg.notes}</dd></>}
        {needs.length > 0 && (
          <>
            <dt className="maint-dl-head">Each visit needs</dt>
            {needs.map((l) => <Fragment key={l.label}><dt>{l.label}</dt><dd>{l.text}</dd></Fragment>)}
          </>
        )}
      </dl>
      {pkg.parent && (
        <p className="lib-date">
          A layer: its tasks go on <Link to={packagePath(pkg.parent.id)}>{pkg.parent.name}</Link>&apos;s work order on the days it visits.
        </p>
      )}
      {pkg.layers?.length > 0 && (
        <p className="lib-date">
          Layers on its visits: {pkg.layers.map((l, i) => <span key={l.id}>{i > 0 && ", "}<Link to={packagePath(l.id)}>{l.name}</Link></span>)}.
        </p>
      )}
    </section>
  );
}

function NextVisits({ pkg, today, onRaise }) {
  const visits = pkg.next_visits || [];
  const [busy, setBusy] = useState(false);
  // Raise the next visit's work order now, on its own (nothing else that's due).
  const canRaise = pkg.status === "active" && !pkg.parent && visits.length > 0 && !visits[0].open_work_order;
  return (
    <section className="card">
      <div className="maint-head maint-wrap"><h2>{visits[0]?.open_work_order ? "Open and next visits" : "Next visits"}</h2>
        {canRaise && (
          <button type="button" className="secondary sm" disabled={busy}
                  onClick={async () => { setBusy(true); await onRaise(); setBusy(false); }}>
            {busy ? "Raising…" : `Raise the ${fmtDate(visits[0].on)} visit now`}
          </button>
        )}
      </div>
      {visits.length === 0 ? (
        <p className="lib-date">
          {pkg.status === "paused" ? "None while it's paused."
            : pkg.status === "retired" ? "None: it's retired."
              : pkg.parent ? <>Its tasks go on <Link to={packagePath(pkg.parent.id)}>{pkg.parent.name}</Link>&apos;s visits.</>
                : "None planned yet."}
        </p>
      ) : (
        <div className="maint-scroll"><table className="lib-table">
          <thead><tr><th>Visit</th><th>Tasks</th><th>What's done</th></tr></thead>
          <tbody>
            {visits.map((v) => (
              <tr key={v.on} className="maint-plain-row">
                <td className="maint-nowrap">
                  {visitDay(v.on, today)}
                  {v.open_work_order && (
                    <div>
                      <Link to={workOrderPath(v.open_work_order.id)}>#{v.open_work_order.number} open</Link>
                      {v.open_work_order.late && <> <Chip tone="danger">late</Chip></>}
                    </div>
                  )}
                </td>
                <td>{v.tasks}</td>
                <td className="lib-date">{visitTasksText(v.task_ids, pkg.tasks) || "—"}</td>
              </tr>
            ))}
          </tbody>
        </table></div>
      )}
    </section>
  );
}

function Tasks({ pkg }) {
  const tasks = pkg.tasks || [];
  return (
    <section className="card">
      <div className="maint-head"><h2>Tasks ({tasks.length})</h2></div>
      {tasks.length === 0 ? <p className="lib-date">No tasks in it yet. Add them from the Explorer&apos;s LSA tab.</p> : (
        <div className="maint-scroll"><table className="lib-table">
          <thead><tr><th>Task</th><th>On</th><th>On which visits</th><th>Interval</th><th>Next due</th><th>Last done</th></tr></thead>
          <tbody>
            {tasks.map((t) => (
              <tr key={t.task_id} className="maint-plain-row">
                <td>
                  {t.name}
                  {t.owed && <> <Chip tone="warning" title="Not done on the last visit: it goes on the next one">Owed</Chip></>}
                  {t.retired && <> <Chip>Retired</Chip></>}
                  {t.suppresses?.length > 0 && <div className="lib-date">covers {t.suppresses.map((s) => s.name).join(", ")}</div>}
                </td>
                <td><SubjectCell subject={t.subject} /></td>
                <td className="maint-nowrap">{visitRuleText(t)}</td>
                <td className="lib-date maint-nowrap">every {t.interval} {unitWord(t.interval, t.unit)}</td>
                <td className="maint-nowrap"><DueChip task={t} /></td>
                <td className="lib-date maint-nowrap">{fmtDate(t.last_done)}</td>
              </tr>
            ))}
          </tbody>
        </table></div>
      )}
    </section>
  );
}

function WorkOrders({ pkg, navigate }) {
  const rows = pkg.work_orders || [];
  return (
    <section className="card">
      <div className="maint-head"><h2>Recent work orders</h2></div>
      {rows.length === 0 ? <p className="lib-date">None raised yet.</p> : (
        <div className="maint-scroll"><table className="lib-table">
          <thead><tr><th>#</th><th>Visit</th><th>Outcome</th><th>Lines</th></tr></thead>
          <tbody>
            {rows.map((w) => (
              <tr key={w.id} className="lib-row" onClick={rowOpen(navigate, workOrderPath(w.id))}>
                <td><RowLink to={workOrderPath(w.id)}>#{w.number}</RowLink></td>
                <td className="maint-nowrap">{fmtDate(w.visit_on || w.due)}</td>
                <td className={w.overdue ? "maint-overdue" : undefined}>{outcomeText(w)}</td>
                <td className="lib-date maint-nowrap">{linesText(w) || "—"}</td>
              </tr>
            ))}
          </tbody>
        </table></div>
      )}
    </section>
  );
}

// Edit, beside the page: name, timing, tolerance, trade, notes and each task's visit rule.
// Saves only what changed, in one update.
function EditPane({ pkg, phone, onClose, onSaved }) {
  const [form, setForm] = useState(() => initialForm(pkg));
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(null);
  const heading = useRef(null);
  useEffect(() => { heading.current?.focus(); }, []);
  useEffect(() => {
    const onKey = (e) => { if (e.key === "Escape" && !busy) onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [busy, onClose]);
  const set = (key) => (e) => setForm((f) => ({ ...f, [key]: e.target.value }));
  const setRule = (taskId, patch) => setForm((f) => ({ ...f, rules: { ...f.rules, [taskId]: { ...f.rules[taskId], ...patch } } }));
  const problem = formProblem(form, pkg);
  const body = editBody(pkg, form);
  const nothing = Object.keys(body).length === 0;
  const layer = !!pkg.parent;
  const patterns = patternsFor({ ...form, timing: layer ? "fixed" : form.timing });
  const pattern = patterns.includes(form.pattern) ? form.pattern : patterns[0];
  const save = async (e) => {
    e.preventDefault();
    if (problem || nothing) return;
    setBusy(true);
    setFailed(null);
    try {
      onSaved(await updatePackage(pkg.id, body));
    } catch (err) {
      setFailed(err.message);
      setBusy(false);
    }
  };
  return (
    <TablePane title="Edit package" subject={pkg.name} phone={phone} busy={busy} headingRef={heading} onClose={onClose}
               className="pkg-edit">
      <form className="pkg-edit-form" onSubmit={save}>
        <Field label="Name" text={form.name}><input value={form.name} maxLength={200} onChange={set("name")} /></Field>
        {!layer && (
          <Field label="Dates">
            <select value={form.timing} onChange={set("timing")}>
              <option value="fixed">Set dates</option>
              <option value="from_last_visit">Counted from the last visit</option>
            </select>
          </Field>
        )}
        <div className="pk-dialog-row">
          <Field label="Every"><input type="number" min="1" step="1" inputMode="numeric" value={form.every} onChange={set("every")} /></Field>
          <Field label="Unit">
            <select value={form.unit} onChange={set("unit")}>{PACKAGE_UNITS.map((u) => <option key={u} value={u}>{u}</option>)}</select>
          </Field>
        </div>
        {form.unit === "months" && patterns.length > 1 && (
          <Field label="In the month">
            <select value={pattern} onChange={set("pattern")}>
              <option value="weekday">On a day of the week</option>
              <option value="day">On a date</option>
            </select>
          </Field>
        )}
        {pattern === "weekday" && (
          <div className="pk-dialog-row">
            {form.unit === "months" && (
              <Field label="Which">
                <select value={form.nth} onChange={set("nth")}>{NTHS.map(([v, w]) => <option key={v} value={v}>{w}</option>)}</select>
              </Field>
            )}
            <Field label="On">
              <select value={form.weekday} onChange={set("weekday")}>{WEEKDAYS.map((d) => <option key={d} value={d}>{dayName(d)}</option>)}</select>
            </Field>
          </div>
        )}
        {pattern === "day" && (
          <Field label="Day of the month"><input type="number" min="1" max="31" step="1" inputMode="numeric" value={form.day} onChange={set("day")} /></Field>
        )}
        {layer ? (
          <p className="lib-date">A layer visits on some of {pkg.parent.name}&apos;s set dates; its on-time window is {pkg.parent.name}&apos;s.</p>
        ) : (
          <div className="pk-dialog-row">
            <Field label="On time within (0: none)">
              <input type="number" min="0" step={form.toleranceUnit === "days" ? "1" : "any"} inputMode="decimal" value={form.tolerance} onChange={set("tolerance")} />
            </Field>
            <Field label="Of">
              <select value={form.toleranceUnit} onChange={set("toleranceUnit")}>
                <option value="days">days after</option>
                <option value="hours">hours after</option>
              </select>
            </Field>
          </div>
        )}
        {!layer && pkg.subject?.kind === "position" && (
          <fieldset className="pkg-rules pkg-shut">
            <legend>Shutdown</legend>
            <label className="mt-mode">
              <input type="checkbox" checked={form.shutdown} onChange={(e) => setForm((f) => ({ ...f, shutdown: e.target.checked }))} />
              {" "}Each visit is a shutdown: it takes {pkg.subject?.name || "the position"} off-line
            </label>
            {form.shutdown && (
              <>
                <div className="pk-dialog-row">
                  <Field label="Off-line for (hours)"><input type="number" min="0" step="any" inputMode="decimal" value={form.shutHours} onChange={set("shutHours")} placeholder="e.g. 72" /></Field>
                  <Field label="Cost each shut (optional)"><input type="number" min="0" step="any" inputMode="decimal" value={form.shutCost} onChange={set("shutCost")} /></Field>
                </div>
                <label className="mt-mode">
                  <input type="checkbox" checked={form.shutIdle} onChange={(e) => setForm((f) => ({ ...f, shutIdle: e.target.checked }))} />
                  {" "}Items not worked on keep ageing during the shut
                </label>
                <p className="lib-date">Its tasks are the work done at each shut. A repairable RBD on {pkg.subject?.name || "the position"} reads it as a planned outage.</p>
              </>
            )}
          </fieldset>
        )}
        <Field label="Trade (optional)" text={form.trade}><input value={form.trade} maxLength={200} onChange={set("trade")} placeholder="e.g. Fitter" /></Field>
        <Field label="Notes (optional)" text={form.notes} max={2000}>
          <textarea rows={3} value={form.notes} maxLength={2000} onChange={set("notes")} />
        </Field>
        {pkg.tasks?.length > 0 && (
          <fieldset className="pkg-rules">
            <legend>On which visits</legend>
            {pkg.tasks.map((t) => {
              const r = form.rules[t.task_id] || { rule: "every", nth: "" };
              return (
                <div key={t.task_id} className="pkg-rule">
                  <span className="pkg-rule-name">{taskLabel(t, pkg.tasks)}</span>
                  <select aria-label={`${taskLabel(t, pkg.tasks)}: on which visits`} value={r.rule}
                          onChange={(e) => setRule(t.task_id, { rule: e.target.value, nth: e.target.value === "nth" ? r.nth || "2" : "" })}>
                    <option value="every">Every visit</option>
                    <option value="nth">Every Nth visit</option>
                  </select>
                  {r.rule === "nth" && (
                    <input aria-label={`${taskLabel(t, pkg.tasks)}: every how many visits`} className="pkg-rule-n" type="number" min="2" max="100" step="1"
                           inputMode="numeric" value={r.nth} onChange={(e) => setRule(t.task_id, { nth: e.target.value })} />
                  )}
                </div>
              );
            })}
          </fieldset>
        )}
        <p className="lib-date">Work orders already raised stay as they are; the change applies from the next one.</p>
        {(failed || (problem && !nothing)) && <p className="field-error" role="alert">{failed || problem}</p>}
        <div className="pkg-edit-actions">
          <button type="submit" disabled={busy || !!problem || nothing}>{busy ? "Saving…" : "Save changes"}</button>
          <button type="button" className="secondary" onClick={onClose} disabled={busy}>Cancel</button>
        </div>
      </form>
    </TablePane>
  );
}
