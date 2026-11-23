import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { getForecastStart, quickForecast } from "../api.js";
import { SectionHeader } from "../components/SectionPage.jsx";
import Card, { CardHeader } from "../components/ui/Card.jsx";
import Chip from "../components/ui/Chip.jsx";
import SegmentedControl from "../components/ui/SegmentedControl.jsx";
import Section, { AddRow } from "../components/ui/Section.jsx";
import Field from "../components/ui/Field.jsx";
import InputGroup, { Addon } from "../components/ui/InputGroup.jsx";
import { TextInput, TextArea } from "../components/ui/Controls.jsx";
import Select from "../components/Select.jsx";
import ResultSummary, { ResultDetails } from "../components/ui/ResultSummary.jsx";
import LoadFailed from "../components/LoadFailed.jsx";
import ModelPicker from "../components/ModelPicker.jsx";
import StrategyUnit from "../components/StrategyUnit.jsx";
import FleetSparesCard from "../components/FleetSparesCard.jsx";
import Plot from "../components/Plot.jsx";
import { ACCENT, INK } from "../plotTheme.js";
import { formatCost, workspaceCurrency } from "../money.js";
import { downloadCsv } from "../csv.js";
import { unitInText } from "../components/unitText.js";
import { strategyUnit } from "../strategyTools.js";
import { VIEWS, fromParam, parseAges, viewOf, whenNext, whenText } from "../sparesForecast.js";
import {
  BLANK, BLANK_WORK, EFFECTS, HORIZON_OPTIONS, RUNNING, WORK_UNITS, answerOf, boundText, formFromStart, horizonWords,
  isCalendar, isHours, kindWords, lineCells, missing, requestOf, seriesOf, viewKey,
} from "../quickForecast.js";
import "./ForecastTool.css";

// Decisions › Forecasts › Spares, Hours and Cost forecast: one quick forecast tool as a sentence
// (forecast plan step 1, Nov 2026; quickForecast.js says what each part does). "[1] unit, running
// [12 h a week], over the next [12 months]", then work on a schedule and/or a part that fails. Each
// view asks only its own "each time" and "if it fails"; the answer updates as you type, with no
// Forecast button. A scratch pad: nothing is saved. Opened from an Explorer node (Open in ›, ?from=)
// it starts filled in from there and names it, with a link back.

const HELP = { guide: "forecast-tools" };
const sig3 = (v) => Number(v).toLocaleString("en-GB", { maximumSignificantDigits: 3 });
const today = () => {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
};

// The view's own extra for a clause: hours on Hours, a cost on Costs, spares on Spares.
function EachTime({ view, work, onWork, currency }) {
  if (view === "hours") {
    return (
      <InputGroup label="Each time">
        <TextInput inputMode="decimal" aria-label="Hours each time" value={work.hoursEach} onChange={(e) => onWork({ hoursEach: e.target.value })} />
        <Addon>h</Addon>
      </InputGroup>
    );
  }
  if (view === "costs") {
    return (
      <InputGroup label="Each time">
        <Addon>{currency}</Addon>
        <TextInput inputMode="decimal" aria-label="Cost each time" value={work.costEach} onChange={(e) => onWork({ costEach: e.target.value })} />
      </InputGroup>
    );
  }
  return (
    <InputGroup label="Each time">
      <TextInput inputMode="decimal" className="ft-n" aria-label="Spares each time" value={work.sparesEach} onChange={(e) => onWork({ sparesEach: e.target.value })} />
      <Addon>×</Addon>
      <TextInput aria-label="Which spare" placeholder="e.g. lithium grease" value={work.spareName} onChange={(e) => onWork({ spareName: e.target.value })} />
    </InputGroup>
  );
}

function IfItFails({ view, form, set, currency }) {
  if (view === "hours") {
    return (
      <InputGroup label="If it fails">
        <TextInput inputMode="decimal" aria-label="Hours if it fails" value={form.hoursIfFails} onChange={(e) => set({ hoursIfFails: e.target.value })} />
        <Addon>h</Addon>
      </InputGroup>
    );
  }
  if (view === "costs") {
    return (
      <InputGroup label="If it fails">
        <Addon>{currency}</Addon>
        <TextInput inputMode="decimal" aria-label="Cost if it fails" value={form.costIfFails} onChange={(e) => set({ costIfFails: e.target.value })} />
      </InputGroup>
    );
  }
  return <span className="ft-words">a like part each time</span>;
}

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

function NotCounted({ out, view }) {
  const key = viewKey(view);
  const t = key === "spares" ? out.totals.spares : out.totals[key];
  const gaps = t?.leaves_out || [];
  if (!gaps.length) return null;
  return (
    <section className="ft-gaps" aria-label="Not counted">
      <h3 className="ft-h">Not counted</h3>
      <ul>{gaps.map((g) => <li key={g}>{g}</li>)}</ul>
      <p className="lib-date">The total is what&apos;s known: it leaves these out rather than guess them.</p>
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
      <p className="lib-date">From the expected counts: the {String(fc.period_label).replace(/s$/, "")} by which each spare is likely used.{w.more ? ` ${w.more.toLocaleString("en-GB")} more after these.` : ""}</p>
    </section>
  );
}

export default function ForecastTool() {
  const location = useLocation();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const view = viewOf(location.pathname);
  const from = fromParam(params);
  const fromKey = from ? `${from.kind}:${from.id}:${params.get("root") || ""}` : "";
  const [form, setForm] = useState(() => (view.value === "spares" ? { ...BLANK, part: true } : { ...BLANK, work: { ...BLANK_WORK } }));
  const [model, setModel] = useState(null);
  const [typedUnit, setTypedUnit] = useState("");
  const [start, setStart] = useState({ key: "", data: null, error: null });
  const [run, setRun] = useState({ busy: false, out: null, error: null, sent: null });
  const seq = useRef(0);
  const set = (patch) => setForm((f) => ({ ...f, ...patch }));
  const setWork = (patch) => setForm((f) => ({ ...f, work: { ...(f.work || BLANK_WORK), ...patch } }));
  const currency = workspaceCurrency();
  const money = (v) => formatCost(v, currency, { sig: 4 });

  // Filled in from an Explorer node, once per node.
  useEffect(() => {
    if (!fromKey || start.key === fromKey) return undefined;
    let live = true;
    getForecastStart({ kind: from.kind, id: from.id, root: params.get("root") })
      .then((data) => {
        if (!live) return;
        setStart({ key: fromKey, data, error: null });
        setForm((f) => formFromStart(data, f));
      })
      .catch((e) => live && setStart({ key: fromKey, data: null, error: e.message }));
    return () => { live = false; };
  }, [fromKey]); // eslint-disable-line react-hooks/exhaustive-deps

  const unit = strategyUnit(model, typedUnit || start.data?.model?.unit || "");
  const why = missing(form, form.part ? model : null, unit);
  const body = useMemo(() => (why ? null : requestOf(form, model, unit, today())), [why, form, model, unit]);
  const sent = body ? JSON.stringify(body) : null;

  // The answer as you type: a short pause, then one call; a later call wins.
  useEffect(() => {
    if (!sent || sent === run.sent) return undefined;
    const mine = ++seq.current;
    const t = setTimeout(() => {
      setRun((r) => ({ ...r, busy: true, error: null }));
      quickForecast(JSON.parse(sent))
        .then((out) => mine === seq.current && setRun({ busy: false, out, error: null, sent }))
        .catch((e) => mine === seq.current && setRun((r) => ({ ...r, busy: false, error: e.message, sent })));
    }, 350);
    return () => clearTimeout(t);
  }, [sent]); // eslint-disable-line react-hooks/exhaustive-deps

  const out = run.out?.status === "ok" && body ? run.out : null;
  const wanted = start.data?.model?.id || null;
  const ages = parseAges(form.ages);
  const otherUnit = form.part && unit && !isHours(unit) && !isCalendar(unit);
  const partNow = unit ? unitInText(unit) : "";

  return (
    <div className="app ft">
      <SectionHeader section="forecasts" title={view.title} purpose={view.purpose} help={HELP}>
        <Chip tone="neutral" className="ft-scratch" title="Nothing here is saved: change anything and the answer follows">Scratch pad: not saved</Chip>
      </SectionHeader>
      {from && (
        <p className="ft-from" role="note">
          {start.error ? <>Couldn&apos;t fill it in from the Explorer: {start.error}</>
            : !start.data ? "Filling it in from the Explorer…"
              : <>From: <Link to={start.data.from.link}>{start.data.from.path || start.data.from.name}</Link>
                {start.data.from.kind === "task" ? ` · ${start.data.from.name}` : start.data.from.kind === "package" ? ` · ${start.data.from.name} (package)` : " and everything below it"}</>}
        </p>
      )}
      <SegmentedControl label="Show" className="ft-views" value={view.value}
                        onChange={(v) => navigate(`${VIEWS.find((x) => x.value === v).path}${location.search}`, { replace: true })}
                        options={VIEWS.map((v) => ({ value: v.value, label: v.label }))} />
      <Card className="ft-inputs">
        {(start.data?.notes || []).length > 0 && (
          <ul className="ft-notes" aria-label="What the Explorer couldn't fill in">{start.data.notes.map((n) => <li key={n}>{n}</li>)}</ul>
        )}
        <div className="ft-sentence" role="group" aria-label="What to forecast">
          <TextInput inputMode="numeric" className="ft-n" aria-label="How many units" value={form.units}
                     disabled={ages.ages?.length > 1} onChange={(e) => set({ units: e.target.value })} />
          <span className="ft-words">{Number(form.units) === 1 ? "unit" : "units"}, running</span>
          {form.runPer !== "all" && (
            <TextInput inputMode="decimal" className="ft-n" aria-label="Hours it runs" value={form.runHours}
                       placeholder="12" onChange={(e) => set({ runHours: e.target.value })} />
          )}
          <Select ariaLabel="How it runs" value={form.runPer} options={RUNNING} onChange={(v) => set({ runPer: v })} />
          <span className="ft-words">, over</span>
          <Select ariaLabel="Horizon" value={form.horizon} options={HORIZON_OPTIONS.map((h) => ({ ...h, label: `the next ${h.label}` }))}
                  onChange={(v) => set({ horizon: v })} />
        </div>

        {form.work ? (
          <Section title="Work on a schedule" action={{ label: "Remove", onClick: () => set({ work: null }), ariaLabel: "Remove the work on a schedule" }}>
            <div className="ft-clause">
              <TextInput aria-label="What the work is" className="ft-name" placeholder="e.g. Grease deck spindles" value={form.work.name}
                         onChange={(e) => setWork({ name: e.target.value })} />
              <span className="ft-words">every</span>
              <InputGroup label="How often">
                <TextInput inputMode="decimal" className="ft-n" aria-label="Every" value={form.work.every} onChange={(e) => setWork({ every: e.target.value })} />
                <Select ariaLabel="Unit of the interval" value={form.work.unit} options={WORK_UNITS} onChange={(v) => setWork({ unit: v })} />
              </InputGroup>
              <span className="ft-words">each time:</span>
              {form.work.effect === "replaces" && view.value === "spares"
                ? <span className="ft-words">a like part each time</span>
                : <EachTime view={view.value} work={form.work} onWork={setWork} currency={currency} />}
            </div>
            {form.part && (
              <div className="ft-clause">
                <span className="ft-words">This work</span>
                <Select ariaLabel="What the work does to the part" value={form.work.effect} options={EFFECTS} onChange={(v) => setWork({ effect: v })} />
              </div>
            )}
          </Section>
        ) : <AddRow onClick={() => set({ work: { ...BLANK_WORK } })}>Work on a schedule</AddRow>}

        {form.part ? (
          <Section title="A part that fails" action={{ label: "Remove", onClick: () => set({ part: false }), ariaLabel: "Remove the part that fails" }}>
            <div className="ft-clause ft-model">
              <ModelPicker key={wanted || "none"} label="Its life" value={model} onChange={setModel} preferSaved wanted={wanted} />
              <StrategyUnit model={model} unit={typedUnit} onUnit={setTypedUnit} />
            </div>
            <div className="ft-clause">
              <span className="ft-words">now</span>
              <InputGroup label="Age now">
                <TextInput inputMode="decimal" className="ft-age" aria-label="How old it is now" value={ages.ages?.length > 1 ? "" : form.ages}
                           placeholder={ages.ages?.length > 1 ? `${ages.ages.length} ages` : "e.g. 9,000"} disabled={ages.ages?.length > 1}
                           onChange={(e) => set({ ages: e.target.value })} />
                {partNow && <Addon>{partNow}</Addon>}
              </InputGroup>
              <span className="ft-words">old · if it fails:</span>
              <IfItFails view={view.value} form={form} set={set} currency={currency} />
            </div>
          </Section>
        ) : <AddRow onClick={() => set({ part: true })}>A part that fails</AddRow>}

        <ResultDetails summary="More options">
          <div className="ft-grid">
            {form.part && (
              <Field label={`A different age for each unit${partNow ? ` (${partNow})` : ""}`} optional help="Spaces or new lines between; it counts the units for you.">
                <TextArea value={ages.ages?.length > 1 ? form.ages : ""} placeholder="e.g. 120 900 1,450" onChange={(e) => set({ ages: e.target.value })} />
              </Field>
            )}
            {form.part && (
              <Field label={`Cost of a spare (${currency})`} optional help="Added to each failure and each replacement. The cost if it fails is all in by default.">
                <TextInput inputMode="decimal" value={form.spareCost} onChange={(e) => set({ spareCost: e.target.value })} />
              </Field>
            )}
            {otherUnit && (
              <Field label={`${partNow} a unit adds a day`}>
                <TextInput inputMode="decimal" value={form.usePerDay} onChange={(e) => set({ usePerDay: e.target.value })} />
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
        {why && <p className="hint compute-why" role="status">{why}</p>}
      </Card>
      {run.error && <LoadFailed what="Couldn't work out the forecast." error={run.error} />}
      {run.out && run.out.status !== "ok" && <div className="card error" role="alert">{run.out.reason}</div>}
      {out && (
        <Card className={"ft-result" + (run.busy ? " is-busy" : "")} aria-busy={run.busy || undefined}>
          <CardHeader title={view.title}
                      subtitle={`${out.units.toLocaleString("en-GB")} ${out.units === 1 ? "unit" : "units"} · ${horizonWords(out.months)}${run.busy ? " · working it out…" : ""}`}
                      actions={<button type="button" className="secondary sm" onClick={() => downloadCsv(csvOf(out, view.value), `${view.title.toLowerCase().replace(/ /g, "-")}.csv`)}>Export CSV</button>} />
          <Answer out={out} view={view.value} money={money} />
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
                         dirty={false} runWord={null} onChange={(v) => set({ spares: v || {} })} />
      )}
    </div>
  );
}
