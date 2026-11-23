import { useEffect, useMemo, useState } from "react";
import { Link, useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { getForecastLines, quickForecast } from "../api.js";
import { SectionHeader } from "../components/SectionPage.jsx";
import Card, { CardHeader } from "../components/ui/Card.jsx";
import Chip from "../components/ui/Chip.jsx";
import SegmentedControl from "../components/ui/SegmentedControl.jsx";
import Section from "../components/ui/Section.jsx";
import Button from "../components/ui/Button.jsx";
import Field from "../components/ui/Field.jsx";
import InputGroup, { Addon } from "../components/ui/InputGroup.jsx";
import { TextInput, TextArea } from "../components/ui/Controls.jsx";
import Select from "../components/Select.jsx";
import ResultSummary, { ResultDetails } from "../components/ui/ResultSummary.jsx";
import LoadFailed from "../components/LoadFailed.jsx";
import ModelPicker from "../components/ModelPicker.jsx";
import FleetSparesCard from "../components/FleetSparesCard.jsx";
import Plot from "../components/Plot.jsx";
import { ACCENT, INK } from "../plotTheme.js";
import { formatCost, workspaceCurrency } from "../money.js";
import { downloadCsv } from "../csv.js";
import { unitInText } from "../components/unitText.js";
import { VIEWS, fromParam, parseAges, viewOf, whenNext, whenText } from "../sparesForecast.js";
import {
  BLANK, BLANK_WORK, EFFECTS, HORIZON_OPTIONS, ON_REPLACE, PART_UNITS, RUNNING, WHATIFS, WORK_UNITS, answerOf, boundText, changeText,
  horizonWords, isCalendar, isHours, kindWords, lineCells, problems, requestOf, seriesOf, viewKey,
} from "../quickForecast.js";
import { cells, headline, metaLine, tableRows } from "../forecastLines.js";
import "./ForecastTool.css";

// Decisions › Forecasts › Spares, Hours and Cost forecast: one quick forecast tool (forecast plan step 1,
// Nov 2026; quickForecast.js says what each part does). One inputs card on a grid: units, running and the
// horizon; then two equal sections, work on a schedule and a part that fails (either can be added or
// removed); More options; and Calculate, bottom right (Derryn, Nov 2026: "there is no calculate button!").
// Results appear only after Calculate, and say "Inputs changed: Calculate again" when the inputs move on.
// Nothing blocks silently: pressed with something missing, Calculate says it beside the field and goes
// there. Each view asks only its own "each time" and "if it fails"; switching views keeps the inputs and
// shows that view of the same result. A scratch pad: nothing is saved. Opened from an Explorer node
// (Open in ›, ?from=) it shows that node's forecast by owner instead.

const HELP = { guide: "forecast-tools" };
const sig3 = (v) => Number(v).toLocaleString("en-GB", { maximumSignificantDigits: 3 });
const today = () => {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
};

function Lines({ out, view, money }) {
  const key = viewKey(view);
  const head = key === "hours" ? "Hours" : key === "cost" ? "Cost" : "Spares";
  return (
    <div className="maint-scroll">
      <table className="lib-table ft-table ft-lines">
        <caption className="sr-only">The forecast by owner</caption>
        <thead><tr><th scope="col">Owner</th><th scope="col" className="num">Times</th><th scope="col" className="num">{head}</th><th scope="col">Kind of number</th></tr></thead>
        <tbody>{out.lines.map((l) => {
          const c = lineCells(l, view, money);
          return (
            <tr key={l.id}>
              <th scope="row">
                <span className="ft-owner">{l.owner_kind === "failure" ? `${l.owner}: failures` : l.owner}</span>
                <span className="ft-owner-meta">{l.owner_kind === "failure" ? "If it fails (corrective)"
                  : l.replaces ? `Replaces the part every ${l.every.value.toLocaleString("en-GB")} ${l.every.unit}`
                    : `Every ${l.every.value.toLocaleString("en-GB")} ${l.every.unit}`}</span>
                {l.note && <span className="ft-owner-meta">{l.note}</span>}
              </th>
              <td className="num">{c.times}</td>
              <td className="num">{c.amount ?? <span className="ft-gap" title={c.gap || ""}>{c.gap ? "not given" : "—"}</span>}</td>
              <td><span className="ft-kind">{kindWords(l)}</span></td>
            </tr>
          );
        })}</tbody>
      </table>
    </div>
  );
}

function Chart({ out, view, money }) {
  const s = seriesOf(out, view);
  const y = s.map((r) => r.value);
  if (!y.some((v) => v > 0)) return null;
  const label = String(out.period_label).replace(/s$/, "");
  const key = viewKey(view);
  const what = key === "hours" ? "Labour hours" : key === "cost" ? "Cost" : "Spares used";
  return (
    <>
      <Plot
        data={[{
          type: "bar", x: s.map((r) => r.period), y, marker: { color: ACCENT },
          error_y: { type: "data", symmetric: false, color: INK, thickness: 1, width: 3,
            array: s.map((r) => Math.max(0, r.high - r.value)), arrayminus: s.map((r) => Math.max(0, r.value - r.low)) },
          hovertemplate: key === "cost" ? "%{y:,.0f}<extra></extra>" : "%{y:.3s}<extra></extra>",
        }]}
        layout={{ height: 220, bargap: 0.35,
          xaxis: { title: { text: label[0].toUpperCase() + label.slice(1) }, tick0: 1, dtick: Math.max(1, Math.ceil(y.length / 12)) },
          yaxis: { title: { text: `${what} a ${label}` }, rangemode: "tozero" } }}
      />
      {out.part && <p className="rs-note">Whiskers: each {label}’s likely range (90% two-sided).</p>}
    </>
  );
}

function ByPeriod({ out, view, money }) {
  const key = viewKey(view);
  const s = seriesOf(out, view);
  const fmt = key === "hours" ? (v) => `${sig3(v)} h` : key === "cost" ? money : sig3;
  const label = String(out.period_label).replace(/s$/, "");
  return (
    <div className="maint-scroll">
      <table className="lib-table ft-table">
        <caption className="sr-only">By {label}</caption>
        <thead><tr><th scope="col">{label[0].toUpperCase() + label.slice(1)}</th><th scope="col" className="num">Times done</th>
          {out.part && <th scope="col" className="num">Failures</th>}<th scope="col" className="num">{key === "hours" ? "Hours" : key === "cost" ? "Cost" : "Spares"}</th>
          {out.part && <th scope="col" className="num">Likely range (90% two-sided)</th>}</tr></thead>
        <tbody>{s.map((r) => (
          <tr key={r.period}><td className="num">{r.period}</td><td className="num">{sig3(r.work)}</td>
            {out.part && <td className="num">{sig3(r.failures)}</td>}<td className="num">{fmt(r.value)}</td>
            {out.part && <td className="num">{fmt(r.low)} to {fmt(r.high)}</td>}</tr>
        ))}</tbody>
      </table>
    </div>
  );
}

function csvOf(out, view) {
  const key = viewKey(view);
  const s = seriesOf(out, view);
  const n4 = (v) => (v == null || !Number.isFinite(Number(v)) ? "" : Number(Number(v).toPrecision(4)));
  return [[String(out.period_label).replace(/s$/, ""), "times_done", "failures", key, `${key}_p5`, `${key}_p95`],
    ...s.map((r) => [r.period, n4(r.work), n4(r.failures), n4(r.value), n4(r.low), n4(r.high)])];
}

function Answer({ out, view, money }) {
  const a = answerOf(out, view, money);
  const fail = out.lines.find((l) => l.owner_kind === "failure");
  const work = out.lines.find((l) => l.owner_kind === "task");
  const notes = [];
  if (work?.number === "certain" && !fail) notes.push("Certain: a schedule, no chance involved.");
  if (work?.number === "certain") notes.push("Assumes it was just done.");
  const bound = boundText(out);
  if (bound) notes.push(bound);
  notes.push(`Running ${out.running.text}.`);
  return (
    <ResultSummary sentence={<b className="ft-lead">{a.lead}</b>}
                   stats={a.detail}>
      {notes.join(" ")}
    </ResultSummary>
  );
}

// Supporting work (forecast plan step 7): its worth, and the answer with it dropped or stretched beside the
// plan as recorded. A comparison: nothing is saved, and the worth is added to no total.
function WhatIf({ out, view, money }) {
  if (!out.worth && !out.whatif) return null;
  const key = viewKey(view);
  const alt = out.whatif;
  const change = alt && key !== "spares" ? changeText(out.totals[key], alt.totals?.[key], view, money) : null;
  const fails = (lines) => (lines || []).find((l) => l.owner_kind === "failure")?.times?.expected;
  return (
    <section className="ft-whatif" aria-label="What if">
      {out.worth && <p className="ft-worth">{out.worth.words}{out.worth.costs != null ? " a year" : ""}.</p>}
      {alt && (
        <p className="ft-whatif-line">
          <b>{alt.plan.drop ? "Not done" : `Every ${alt.plan.interval.toLocaleString("en-GB")}`}:</b>{" "}
          {change ? <>{change.changed} against {change.planned} as planned ({change.diff}). </> : null}
          {fails(alt.lines) != null && fails(out.lines) != null
            ? <>Failures {sig3(fails(alt.lines))} against {sig3(fails(out.lines))}. </> : null}
          The failure rate × {Number(alt.ratio.mult).toLocaleString("en-GB", { maximumSignificantDigits: 3 })} on average
          {alt.ratio.overdue_share > 0 && alt.ratio.overdue_share < 1 ? ` (overdue ${Math.round(alt.ratio.overdue_share * 100)}% of the time)` : ""}.
          {alt.approximate && <> <Chip tone="warning" title="The interval is more than a fifth of the part's mean life: the averaged ratio is a rough guide here">Approximate</Chip></>}
        </p>
      )}
    </section>
  );
}

function NotCounted({ out, view }) {
  const key = viewKey(view);
  const t = key === "spares" ? out.totals.spares : out.totals[key];
  const gaps = t?.leaves_out || [];
  if (!gaps.length) return null;
  return (
    <section className="ft-gaps" aria-label="Not counted">
      <h3 className="ft-h">Not counted</h3>
      <ul>{gaps.map((g) => <li key={g}>{g}</li>)}</ul>
      <p className="rs-note">The total is what&apos;s known: it leaves these out rather than guess them.</p>
    </section>
  );
}

function WhenNext({ fc }) {
  const w = whenNext(fc);
  if (!w.items.length) return null;
  return (
    <section className="ft-next" aria-label="When next">
      <h3 className="ft-h">When next</h3>
      <ol className="ft-next-list">{w.items.map((x) => <li key={x.n}>{whenText(fc, x)}</li>)}</ol>
      <p className="rs-note">From the expected counts: the {String(fc.period_label).replace(/s$/, "")} by which each spare is likely used.{w.more ? ` ${w.more.toLocaleString("en-GB")} more after these.` : ""}</p>
    </section>
  );
}

function ToolHeader({ view }) {
  const location = useLocation();
  const navigate = useNavigate();
  return (
    <>
      <SectionHeader section="forecasts" title={view.title} purpose={view.purpose} help={HELP}>
        <Chip tone="neutral" className="ft-scratch" title="Nothing here is saved: change anything and the answer follows">Scratch pad: not saved</Chip>
      </SectionHeader>
      <SegmentedControl label="Show" className="ft-views" value={view.value}
                        onChange={(v) => navigate(`${VIEWS.find((x) => x.value === v).path}${location.search}`, { replace: true })}
                        options={VIEWS.map((v) => ({ value: v.value, label: v.label }))} />
    </>
  );
}

// Whole money from 100 up ($16,313, not $16,300); 3 significant figures below.
function useMoney() {
  const currency = workspaceCurrency();
  return (v) => (Math.abs(v) >= 100 ? formatCost(Math.round(v), currency, { sig: Math.max(3, String(Math.round(Math.abs(v))).length) })
    : formatCost(v, currency, { sig: 3 }));
}

// Opened from the Explorer (Open in ›): no form; the records are the inputs, shown as lines by owner.
function FromRecords({ view, from, root }) {
  const money = useMoney();
  const [months, setMonths] = useState("12");
  const [got, setGot] = useState({ key: "", out: null, error: null });
  // Supporting tasks changed for a what-if (step 7): {task_id: {mode: "" | "stretch" | "drop", every}}.
  const [changes, setChanges] = useState({});
  const whatif = whatifOf(changes);
  const key = `${from.kind}:${from.id}:${root || ""}:${months}:${JSON.stringify(whatif)}`;
  useEffect(() => {
    let live = true;
    const t = setTimeout(() => {
      getForecastLines({ kind: from.kind, id: from.id, root, months, whatif })
        .then((out) => live && setGot({ key, out, error: null }))
        .catch((e) => live && setGot({ key, out: null, error: e.message }));
    }, Object.keys(whatif).length ? 350 : 0);
    return () => { live = false; clearTimeout(t); };
  }, [key]); // eslint-disable-line react-hooks/exhaustive-deps
  const out = got.out;
  const busy = got.key !== key;
  const h = out ? headline(out, view.value, money) : null;
  const rows = out ? tableRows(out.lines) : [];
  const total = out?.lines?.totals;
  const alt = out?.whatif || null;
  const altKey = view.value === "hours" ? "hours" : view.value === "costs" ? "cost" : "times";
  const altFmt = altKey === "hours" ? (v) => `${sig3(v)} h` : altKey === "cost" ? money : sig3;
  const altOf = (id) => {
    const x = (alt?.lines?.lines || []).find((l) => l.id === id);
    const v = x?.[altKey]?.expected;
    if (x == null) return id.startsWith("task:") && whatif[id.slice(5)]?.drop ? "not done" : "—";
    return v == null ? "—" : altFmt(v);
  };
  const altTotal = alt ? (altKey === "times" ? null : alt.lines.totals[altKey]?.expected) : null;
  return (
    <div className="app ft">
      <ToolHeader view={view} />
      {/* A refusal or failure shows once, in the error box: the note is only for where it came from. */}
      {!got.error && <p className="ft-from" role="note">
        {!out ? "Reading the records…"
            : <>From: <Link to={out.from.link} title="Back to the Explorer">{out.from.path || out.from.name}</Link>
              {out.from.kind === "task" ? ` · ${out.from.name}` : out.from.kind === "package" ? ` · ${out.from.name} (package)` : " and everything below it"}</>}
      </p>}
      {got.error && <LoadFailed what="Couldn't forecast it from the Explorer." error={got.error} />}
      {out && (
        <Card className={"ft-result" + (busy ? " is-busy" : "")} aria-busy={busy || undefined}>
          <CardHeader title={view.title} subtitle={metaLine(out)}
                      actions={<Select ariaLabel="Horizon" value={months} onChange={setMonths}
                                       options={HORIZON_OPTIONS.map((o) => ({ ...o, label: `Next ${o.label}` }))} />} />
          <ResultSummary sentence={<b className="ft-lead">{h.lead}</b>} stats={h.tiles}>
            Ranges are 90% two-sided. Each task is counted from its schedule (certain); failures are worked out
            from each life model, as the plan leaves them. Nothing here is written back.
          </ResultSummary>
          {(out.lines.worth || []).length > 0 && (
            <SupportWhatIf worth={out.lines.worth} changes={changes} setChanges={setChanges} alt={alt} busy={busy} />
          )}
          <div className="maint-scroll">
            <table className="lib-table ft-table ft-lines">
              <caption className="sr-only">The forecast by owner</caption>
              <thead><tr><th scope="col">Owner</th><th scope="col" className="num">Times</th><th scope="col" className="num">Hours</th>
                <th scope="col" className="num">Cost</th>{alt && <th scope="col" className="num">With your changes</th>}
                <th scope="col">Spares</th><th scope="col">Kind of number</th></tr></thead>
              <tbody>{rows.map((r) => {
                const c = cells(r.line, money);
                const amount = (a) => (a.text != null ? a.text : <span className="ft-gap" title={a.gap || ""}>{a.gap ? "not known" : "—"}</span>);
                return (
                  <tr key={r.id} className={r.depth ? "ft-sub" : r.group ? "ft-group" : undefined}>
                    <th scope="row">
                      <span className="ft-owner">{r.link && !r.depth ? <Link to={r.link}>{r.owner}</Link> : r.owner}</span>
                      {r.meta && <span className="ft-owner-meta">{r.meta}</span>}
                      {r.marker?.assumed && <Chip tone="warning" className="ft-assumed" title={r.marker.title}>Assumed</Chip>}
                    </th>
                    <td className="num">{c.times}</td><td className="num">{amount(c.hours)}</td><td className="num">{amount(c.cost)}</td>
                    {alt && <td className="num ft-alt">{r.group ? "" : altOf(r.id)}</td>}
                    <td className="ft-spares">{c.spares}</td><td><span className="ft-kind">{c.number}</span></td>
                  </tr>
                );
              })}</tbody>
              <tfoot><tr><th scope="row">{total.cost.known && total.hours.known ? "Total" : "Total (known)"}</th><td />
                <td className="num">{`${sig3(total.hours.expected || 0)} h`}</td><td className="num">{money(total.cost.expected || 0)}</td>
                {alt && <td className="num ft-alt">{altTotal == null ? "" : altFmt(altTotal)}</td>}<td /><td /></tr></tfoot>
            </table>
          </div>
          {(out.lines.not_counted || []).length > 0 && (
            <section className="ft-gaps" aria-label="Not counted">
              <h3 className="ft-h">Not counted</h3>
              <ul>{out.lines.not_counted.map((x, i) => (
                <li key={i}>{x.text}{x.link && x.fix ? <> · <Link to={x.link}>{x.fix}</Link></> : null}</li>
              ))}</ul>
              <p className="rs-note">A total with a gap is the known total: it leaves these out rather than guess them.</p>
            </section>
          )}
          <ResultDetails summary="By month">
            <div className="maint-scroll">
              <table className="lib-table ft-table">
                <caption className="sr-only">By month</caption>
                <thead><tr><th scope="col">From</th><th scope="col" className="num">Tasks</th><th scope="col" className="num">Labour hours</th>
                  <th scope="col" className="num">Planned</th><th scope="col" className="num">Failures</th><th scope="col" className="num">Unplanned</th></tr></thead>
                <tbody>{(out.rows || []).map((r) => (
                  <tr key={r.start}><td>{r.start}</td><td className="num">{r.tasks}</td><td className="num">{sig3(r.labour_hours || 0)} h</td>
                    <td className="num">{money(r.planned_cost || 0)}</td><td className="num">{r.failures == null ? "—" : sig3(r.failures)}</td>
                    <td className="num">{r.unplanned_cost == null ? "—" : money(r.unplanned_cost)}</td></tr>
                ))}</tbody>
              </table>
            </div>
          </ResultDetails>
        </Card>
      )}
    </div>
  );
}

// {task_id: {mode, every}} → the what-if the server takes ({task_id: {drop} | {interval}}), changed tasks only.
function whatifOf(changes) {
  const out = {};
  for (const [id, c] of Object.entries(changes)) {
    if (c.mode === "drop") out[id] = { drop: true };
    else if (c.mode === "stretch" && Number(c.every) > 0) out[id] = { interval: Number(c.every) };
  }
  return out;
}

// The supporting tasks here (forecast plan step 7): each one's worth (a comparison, on no line), and a
// what-if: stretch it or drop it to see the forecast beside the plan as recorded. Nothing is written.
function SupportWhatIf({ worth, changes, setChanges, alt, busy }) {
  const set = (id, patch) => setChanges((c) => ({ ...c, [id]: { mode: "", every: "", ...(c[id] || {}), ...patch } }));
  return (
    <section className="ft-whatif" aria-label="Supporting tasks: what if">
      <h3 className="ft-h">Supporting tasks: what if</h3>
      <ul className="ft-whatif-list">
        {worth.map((w) => {
          const c = changes[w.task_id] || { mode: "", every: "" };
          const ratio = (alt?.ratios || []).flatMap((r) => r.tasks).find((t) => t.id === w.task_id);
          return (
            <li key={w.task_id}>
              <span className="ft-owner">{w.name}</span>
              <span className="ft-owner-meta">Every {w.interval} {w.unit} (its life assumes every {w.reference} {w.unit}) · {w.words}{w.avoids_cost != null ? " in the horizon" : ""} (failure rate × {w.k} if it isn&apos;t done).</span>
              <div className="ft-clause">
                <Select ariaLabel={`What if: ${w.name}`} value={c.mode} options={WHATIFS} onChange={(v) => set(w.task_id, { mode: v })} />
                {c.mode === "stretch" && (
                  <InputGroup label={`${w.name}: stretched interval`}>
                    <TextInput inputMode="decimal" className="ft-n" aria-label={`${w.name}: stretched to every`} value={c.every}
                               onChange={(e) => set(w.task_id, { every: e.target.value })} />
                    <Addon>{w.unit}</Addon>
                  </InputGroup>
                )}
                {ratio && <span className="ft-words">failure rate × {Number(ratio.mult).toLocaleString("en-GB", { maximumSignificantDigits: 3 })} on average</span>}
                {ratio?.approximate && <Chip tone="warning" title="The interval is more than a fifth of the part's mean life: the averaged ratio is a rough guide">Approximate</Chip>}
              </div>
            </li>
          );
        })}
      </ul>
      {alt && <p className="rs-note">{busy ? "Working it out… " : ""}The column &quot;With your changes&quot; is the forecast with these changes; the plan as recorded is unchanged and nothing is written.</p>}
    </section>
  );
}

export default function ForecastTool() {
  const location = useLocation();
  const [params] = useSearchParams();
  const view = viewOf(location.pathname);
  const from = fromParam(params);
  if (from) return <FromRecords key={`${from.kind}:${from.id}`} view={view} from={from} root={params.get("root")} />;
  return <SentenceTool view={view} />;
}

function SentenceTool({ view }) {
  const [form, setForm] = useState(() => (view.value === "spares" ? { ...BLANK, part: true } : { ...BLANK, work: { ...BLANK_WORK } }));
  const [model, setModel] = useState(null);
  const [source, setSource] = useState("saved"); // the life picker's source: saved | params
  const [run, setRun] = useState({ busy: false, out: null, error: null, sent: null });
  // The problems shown after Calculate was pressed: each stays beside its field until it's fixed.
  const [asked, setAsked] = useState(new Set());
  const set = (patch) => setForm((f) => ({ ...f, ...patch }));
  const setWork = (patch) => setForm((f) => ({ ...f, work: { ...(f.work || BLANK_WORK), ...patch } }));
  const currency = workspaceCurrency();
  const money = useMoney();

  // A saved model brings its unit; typed parameters take the unit picked (hours by default).
  const unit = form.part ? (model?.unit || (source === "params" ? form.partUnit : "")) : "";
  const probs = problems(form, form.part ? model : null, unit);
  const body = useMemo(() => (probs.length ? null : requestOf(form, model, unit, today())), [probs.length, form, model, unit]); // eslint-disable-line react-hooks/exhaustive-deps
  const errorOf = (field) => (asked.has(field) ? probs.find((p) => p.field === field)?.text || null : null);
  const stale = !!run.out && !!run.sent && JSON.stringify(body) !== run.sent;

  const calculate = (e) => {
    e?.preventDefault();
    if (probs.length) {
      // Never silent: say what blocks it beside each field, and go to the first.
      setAsked(new Set(probs.map((p) => p.field)));
      const first = document.getElementById(`ft-${probs[0].field}`);
      const target = first?.matches("input, textarea, button") ? first : first?.querySelector("input, textarea, button");
      target?.focus();
      return;
    }
    setAsked(new Set());
    const sent = JSON.stringify(body);
    setRun((r) => ({ ...r, busy: true, error: null }));
    quickForecast(body)
      .then((out) => setRun({ busy: false, out, error: null, sent }))
      .catch((err) => setRun((r) => ({ ...r, busy: false, error: err.message, sent })));
  };

  const out = run.out?.status === "ok" ? run.out : null;
  const ages = parseAges(form.ages);
  const otherUnit = form.part && unit && !isHours(unit) && !isCalendar(unit);
  const partNow = unit ? unitInText(unit) : "";
  const viewWord = view.value === "hours" ? "Hours" : view.value === "costs" ? `Cost (${currency})` : "Spares";

  return (
    <div className="app ft">
      <ToolHeader view={view} />
      <form className="ft-form" onSubmit={calculate} noValidate aria-label="What to forecast">
        <Card className="ft-inputs">
          <div className="ft-fields">
            <Field label="Units" id="ft-units" error={errorOf("units")} help={ages.ages?.length > 1 ? "Counted from the ages under More options." : null}>
              <TextInput inputMode="numeric" value={ages.ages?.length > 1 ? String(ages.ages.length) : form.units}
                         disabled={ages.ages?.length > 1} onChange={(e) => set({ units: e.target.value })} />
            </Field>
            <Field label="Running">
              <Select value={form.runPer} options={RUNNING.map((r) => ({ ...r, label: r.value === "all" ? "All the time" : r.value === "day" ? "Hours a day" : "Hours a week" }))}
                      onChange={(v) => set({ runPer: v })} />
            </Field>
            {form.runPer !== "all" && (
              <Field label={form.runPer === "day" ? "Hours a day" : "Hours a week"} id="ft-runHours" error={errorOf("runHours")}>
                <InputGroup label="Hours it runs">
                  <TextInput inputMode="decimal" value={form.runHours} placeholder="12" onChange={(e) => set({ runHours: e.target.value })} />
                  <Addon>h</Addon>
                </InputGroup>
              </Field>
            )}
            <Field label="Horizon">
              <Select value={form.horizon} options={HORIZON_OPTIONS.map((h) => ({ ...h, label: `Next ${h.label}` }))} onChange={(v) => set({ horizon: v })} />
            </Field>
          </div>

          <Section title="Work on a schedule" className="ft-sec"
                   action={form.work ? { label: "Remove", onClick: () => set({ work: null }), ariaLabel: "Remove the work on a schedule" }
                     : { label: "Add", plus: true, onClick: () => set({ work: { ...BLANK_WORK } }), ariaLabel: "Add work on a schedule" }}>
            {!form.work ? <p className="ft-quiet">Not included. Add work done on a schedule (greasing, a test, a planned replacement): no model needed.</p> : (
              <div className="ft-fields">
                <Field label="What's done" optional>
                  <TextInput placeholder="e.g. Grease deck spindles" value={form.work.name} onChange={(e) => setWork({ name: e.target.value })} />
                </Field>
                <Field label="Every" id="ft-every" error={errorOf("every")}>
                  <InputGroup label="How often">
                    <TextInput inputMode="decimal" value={form.work.every} onChange={(e) => setWork({ every: e.target.value })} />
                    <Select ariaLabel="Unit of the interval" value={form.work.unit} options={WORK_UNITS} onChange={(v) => setWork({ unit: v })} />
                  </InputGroup>
                </Field>
                {view.value === "hours" && (
                  <Field label="Hours each time" optional>
                    <InputGroup label="Hours each time, in hours"><TextInput inputMode="decimal" value={form.work.hoursEach} onChange={(e) => setWork({ hoursEach: e.target.value })} /><Addon>h</Addon></InputGroup>
                  </Field>
                )}
                {view.value === "costs" && (
                  <Field label={`Cost each time (${currency})`} optional>
                    <TextInput inputMode="decimal" value={form.work.costEach} onChange={(e) => setWork({ costEach: e.target.value })} />
                  </Field>
                )}
                {view.value === "spares" && !(form.part && form.work.effect === "replaces") && (
                  <Field label="Spares each time" optional>
                    <InputGroup label="How many of which spare">
                      <TextInput inputMode="decimal" className="ft-n" aria-label="How many" value={form.work.sparesEach} onChange={(e) => setWork({ sparesEach: e.target.value })} />
                      <Addon>×</Addon>
                      <TextInput aria-label="Which spare" placeholder="e.g. grease" value={form.work.spareName} onChange={(e) => setWork({ spareName: e.target.value })} />
                    </InputGroup>
                  </Field>
                )}
                {form.part && (
                  <Field label="What it does to the part" id="ft-effect" error={errorOf("effect")}>
                    <Select value={form.work.effect} options={EFFECTS.map((x) => ({ ...x, label: x.label[0].toUpperCase() + x.label.slice(1) }))}
                            onChange={(v) => setWork({ effect: v })} />
                  </Field>
                )}
                {form.part && form.work.effect === "supports" && (
                  <Field label="If it isn't done: failure rate ×" id="ft-impact" optional error={errorOf("impact")}>
                    <TextInput inputMode="decimal" placeholder="e.g. 2" value={form.work.impactK} onChange={(e) => setWork({ impactK: e.target.value })} />
                  </Field>
                )}
                {form.part && form.work.effect === "supports" && (
                  <Field label="What if it's">
                    <Select value={form.work.whatif} options={WHATIFS.map((x) => ({ ...x, label: x.label[0].toUpperCase() + x.label.slice(1) }))}
                            onChange={(v) => setWork({ whatif: v })} />
                  </Field>
                )}
                {form.part && form.work.effect === "supports" && form.work.whatif === "stretch" && (
                  <Field label="Stretched to every" id="ft-whatifEvery" error={errorOf("whatifEvery")}>
                    <InputGroup label="Stretched interval, with its unit">
                      <TextInput inputMode="decimal" value={form.work.whatifEvery} onChange={(e) => setWork({ whatifEvery: e.target.value })} />
                      <Addon>{form.work.unit}</Addon>
                    </InputGroup>
                  </Field>
                )}
              </div>
            )}
          </Section>

          <Section title="A part that fails" className="ft-sec"
                   action={form.part ? { label: "Remove", onClick: () => set({ part: false }), ariaLabel: "Remove the part that fails" }
                     : { label: "Add", plus: true, onClick: () => set({ part: true }), ariaLabel: "Add a part that fails" }}>
            {!form.part ? <p className="ft-quiet">Not included. Add a part with a life model to forecast its failures.</p> : (
              <>
                <div id="ft-life" className="ft-life">
                  <ModelPicker layout="grid" savedFirst typeLabel="Type parameters" value={model} onChange={setModel} preferSaved unit={unit}
                               onSource={setSource}>
                    {source !== "params" ? (model?.unit && (
                      <Field label="Unit">
                        <span className="ft-fixed" title="A saved model brings its own unit">{unitInText(model.unit)} (the model&apos;s)</span>
                      </Field>
                    )) : (
                      <Field label="Unit" id="ft-unit" error={errorOf("unit")} help="Of its age and its life.">
                        <Select value={form.partUnit} options={PART_UNITS} onChange={(v) => set({ partUnit: v })} />
                      </Field>
                    )}
                  </ModelPicker>
                  {errorOf("life") && <p className="field-error" role="alert">{errorOf("life")}</p>}
                </div>
                <div className="ft-fields">
                  <Field label="Age now" id="ft-age" error={errorOf("age")}
                         help={ages.ages?.length > 1 ? `${ages.ages.length} ages under More options.` : "How old it is today."}>
                    <InputGroup label="Age now, with its unit">
                      <TextInput inputMode="decimal" value={ages.ages?.length > 1 ? "" : form.ages} disabled={ages.ages?.length > 1}
                                 placeholder="e.g. 9,000" onChange={(e) => set({ ages: e.target.value })} />
                      {partNow && <Addon>{partNow}</Addon>}
                    </InputGroup>
                  </Field>
                  {view.value === "hours" && (
                    <Field label="Hours if it fails" optional>
                      <InputGroup label="Hours if it fails, in hours"><TextInput inputMode="decimal" value={form.hoursIfFails} onChange={(e) => set({ hoursIfFails: e.target.value })} /><Addon>h</Addon></InputGroup>
                    </Field>
                  )}
                  {view.value === "costs" && (
                    <Field label={`Cost if it fails (${currency})`} optional>
                      <TextInput inputMode="decimal" value={form.costIfFails} onChange={(e) => set({ costIfFails: e.target.value })} />
                    </Field>
                  )}
                  {otherUnit && (
                    <Field label={`${partNow[0].toUpperCase()}${partNow.slice(1)} a unit adds a day`} id="ft-usePerDay" error={errorOf("usePerDay")}>
                      <TextInput inputMode="decimal" value={form.usePerDay} onChange={(e) => set({ usePerDay: e.target.value })} />
                    </Field>
                  )}
                </div>
                {view.value === "spares" && <p className="ft-quiet">If it fails: a like part each time.</p>}
              </>
            )}
          </Section>
          {errorOf("add") && <p className="field-error" role="alert">{errorOf("add")}</p>}

          <ResultDetails summary="More options">
            <div className="ft-fields">
              {form.part && (
                <Field label={`A different age for each unit${partNow ? ` (${partNow})` : ""}`} optional help="Spaces or new lines between; it counts the units for you.">
                  <TextArea value={ages.ages?.length > 1 ? form.ages : ""} placeholder="e.g. 120 900 1,450" onChange={(e) => set({ ages: e.target.value })} />
                </Field>
              )}
              {form.part && (
                <Field label={`Cost of a spare (${currency})`} optional help="Added to each failure and each replacement.">
                  <TextInput inputMode="decimal" value={form.spareCost} onChange={(e) => set({ spareCost: e.target.value })} />
                </Field>
              )}
              {form.work && form.part && form.work.effect === "supports" && (
                <Field label="Grace (% of its interval)" optional help="How far overdue before the impact starts.">
                  <TextInput inputMode="decimal" value={form.work.grace} onChange={(e) => setWork({ grace: e.target.value })} />
                </Field>
              )}
              {form.work && form.part && form.work.effect === "replaces" && (
                <Field label="When the part is replaced">
                  <Select value={form.work.onReplace || "restart"} options={ON_REPLACE} onChange={(v) => setWork({ onReplace: v })} />
                </Field>
              )}
              {form.work && view.value !== "hours" && (
                <Field label="Hours each time" optional><TextInput inputMode="decimal" value={form.work.hoursEach} onChange={(e) => setWork({ hoursEach: e.target.value })} /></Field>
              )}
              {form.work && view.value !== "costs" && (
                <Field label={`Cost each time (${currency})`} optional><TextInput inputMode="decimal" value={form.work.costEach} onChange={(e) => setWork({ costEach: e.target.value })} /></Field>
              )}
              {form.part && view.value !== "hours" && (
                <Field label="Hours if it fails" optional><TextInput inputMode="decimal" value={form.hoursIfFails} onChange={(e) => set({ hoursIfFails: e.target.value })} /></Field>
              )}
              {form.part && view.value !== "costs" && (
                <Field label={`Cost if it fails (${currency})`} optional><TextInput inputMode="decimal" value={form.costIfFails} onChange={(e) => set({ costIfFails: e.target.value })} /></Field>
              )}
            </div>
          </ResultDetails>

          <div className="ft-actions">
            {stale && <span className="ft-stale" role="status">Inputs changed: Calculate again.</span>}
            <Button type="submit" disabled={run.busy}>{run.busy ? "Calculating…" : "Calculate"}</Button>
          </div>
        </Card>
      </form>
      {run.error && <LoadFailed what="Couldn't work out the forecast." error={run.error} />}
      {run.out && run.out.status !== "ok" && <div className="card error" role="alert">{run.out.reason}</div>}
      {!run.out && !run.error && (
        <Card className="ft-result ft-empty">
          <p className="ft-empty-text">{run.busy ? "Working it out…" : <>Set the inputs and press <b>Calculate</b>.</>}</p>
          <p className="ft-quiet">{viewWord} for {Number(form.units) === 1 ? "1 unit" : `${form.units} units`} over the next {form.horizon} months, by month, with the likely range (90% two-sided). Nothing is saved.</p>
        </Card>
      )}
      {out && (
        <Card className={"ft-result" + (run.busy || stale ? " is-busy" : "")} aria-busy={run.busy || undefined}>
          <CardHeader title={view.title}
                      subtitle={stale ? "Inputs changed: Calculate again to update this answer."
                        : `${out.units.toLocaleString("en-GB")} ${out.units === 1 ? "unit" : "units"} · ${horizonWords(out.months)}`}
                      actions={<button type="button" className="secondary sm" onClick={() => downloadCsv(csvOf(out, view.value), `${view.title.toLowerCase().replace(/ /g, "-")}.csv`)}>Export CSV</button>} />
          <Answer out={out} view={view.value} money={money} />
          <WhatIf out={out} view={view.value} money={money} />
          <Lines out={out} view={view.value} money={money} />
          <NotCounted out={out} view={view.value} />
          <Chart out={out} view={view.value} money={money} />
          <ResultDetails summary={`By ${String(out.period_label).replace(/s$/, "")}`}>
            <ByPeriod out={out} view={view.value} money={money} />
          </ResultDetails>
          {view.value === "spares" && out.part && <WhenNext fc={out.part} />}
        </Card>
      )}
      {out?.part && view.value === "spares" && (
        <FleetSparesCard fleet={{ name: "Spares forecast" }} settings={{ ...out.part.settings, spares: form.spares }} forecast={out.part}
                         dirty={stale} runWord="Calculate" onChange={(v) => set({ spares: v || {} })} />
      )}
    </div>
  );
}
