import { useEffect, useState } from "react";
import { listMaintenanceParts } from "../api.js";
import { cleanSection, modeLine, num, sectionDraft } from "../lsaTab.js";
import { workspaceCurrency } from "../money.js";
import { Link, useLocation } from "react-router-dom";
import { explorerHere } from "../products.js";
import { taskKey } from "../explorerRcm.js";
import { Cell, Rows } from "./LsaTask.jsx";
import Field from "./ui/Field.jsx";
import Section from "./ui/Section.jsx";
import { Select, TextArea, TextInput } from "./ui/Controls.jsx";

// "What it needs" (the task's LSA) as a section of the task's details panel (MaintenanceTask):
// Tools and instruments (with the measuring point or channel an instrument reads), Consumables,
// Access and downtime, Method and the task's Instructions. Its Labour (LabourRows) and Parts
// (SparesRows) are fold-outs of their own in the panel (Derryn, 23 Nov 2026). It has no Save of its own: useNeeds holds the
// draft and gives the changed parts (needsBody) to the panel's Save, which sends them with the
// rest of the task.

const SECTIONS = ["labour", "tools", "spares", "consumables", "access", "method", "duration_hours"];

// The draft of a task's needs, from getTaskLsa's answer (null until it has loaded): `body()` is what
// changed (cleaned, as the server keeps it) for updateMaintenanceTask, or {} when nothing did.
export function useNeeds(data) {
  const [draft, setDraft] = useState(null);
  const [instructions, setInstructions] = useState("");
  const [base, setBase] = useState(null);
  useEffect(() => {
    if (!data) { setDraft(null); return; }
    const r = data.task.resources || {};
    const d = Object.fromEntries(SECTIONS.map((k) => [k, sectionDraft(k, r)]));
    setDraft(d);
    setInstructions(data.task.instructions || "");
    setBase({
      ...Object.fromEntries(SECTIONS.map((k) => [k, JSON.stringify(cleanSection(k, d[k]))])),
      instructions: data.task.instructions || "",
    });
  }, [data]);
  const set = (key, value) => setDraft((d) => ({ ...d, [key]: value }));
  const body = () => {
    if (!draft || !base) return {};
    const resources = {};
    for (const k of SECTIONS) {
      const clean = cleanSection(k, draft[k]);
      if (JSON.stringify(clean) !== base[k]) resources[k] = clean;
    }
    return {
      ...(Object.keys(resources).length ? { resources } : {}),
      ...(instructions !== base.instructions ? { instructions } : {}),
    };
  };
  return { draft, instructions, setInstructions, set, body, ready: !!draft };
}

// The line under the heading: what is saved for the task now (its labour and parts are said in
// their own fold-outs).
export function needsTotals(r) {
  const count = (list, one, many) => (list?.length ? `${list.length} ${list.length === 1 ? one : many}` : null);
  const bits = [
    count(r.tools, "tool", "tools"),
    count(r.consumables, "consumable", "consumables"),
    r.access?.downtime_hours != null ? `${num(r.access.downtime_hours)} h downtime` : null,
    r.method ? "method set" : null,
  ].filter(Boolean);
  return bits.length ? bits.join(" · ") : "No tools, consumables or method set yet";
}

export default function NeedsSection({ data, needs, open, onToggle, disabled = false, id = "task-needs" }) {
  const location = useLocation();
  const { draft, instructions, setInstructions, set } = needs;
  const t = data.task;
  const r = t.resources || {};
  return (
    <Section title="What it needs" id={id} className="ruled mt-sec mt-needs"
             action={{ label: open ? "Hide" : "Show", ariaLabel: `${open ? "Hide" : "Show"} what ${t.name} needs`, onClick: onToggle }}
             tip="Its tools, consumables, access and method (its LSA; labour and parts are above). Saved with the task.">
      <p className="field-help lsa-total" role="note" aria-live="polite">{needsTotals(r)}</p>
      {open && (
        <div className="lsa-task">
          {data.modes.length > 0 ? (
            <div className="lsa-modes">
              <span className="lib-date">Serves:</span>
              {/* Each a link to the task's row under that failure mode on the RCM tab. */}
              <ul>{data.modes.map((m) => (
                <li key={m.id}>
                  <Link to={explorerHere(location.pathname, location.search, { sel: taskKey(m.id, t.id), tab: "rcm" })} title="Show this task under the failure mode on the RCM tab">{m.text}</Link>
                  {modeLine(m) && <span className="lib-date"> · {modeLine(m)}</span>}
                </li>
              ))}</ul>
            </div>
          ) : <p className="field-help">Serves no failure mode (a task added directly).</p>}

          <Section title="Tools and instruments" headingLevel={4} className="mt-needs-sub">
            <p className="field-help">Tools and test equipment. An instrument can name the measuring point or channel it reads.</p>
            <Rows label="Tool lines" rows={draft.tools} onRows={(v) => set("tools", v)} blank={{ name: "", qty: "", note: "", point_id: "" }} addLabel="+ Add a tool"
                  render={(x, patch, i) => (
                    <>
                      <Cell label="Tool" className="lsa-wide"><input aria-label={`Tool, line ${i + 1}`} placeholder="e.g. Torque wrench" value={x.name} maxLength={200} disabled={disabled} onChange={(e) => patch({ name: e.target.value })} /></Cell>
                      <Cell label="How many" className="lsa-num"><input type="number" min="0" step="1" inputMode="numeric" aria-label={`How many, line ${i + 1}`} value={x.qty} disabled={disabled} onChange={(e) => patch({ qty: e.target.value })} /></Cell>
                      {data.points.length > 0 && (
                        <Cell label="Reads" className="lsa-wide"><Select aria-label={`Reads, line ${i + 1}`} value={x.point_id} disabled={disabled} onChange={(e) => patch({ point_id: e.target.value })}>
                          <option value="">Reads no point</option>
                          {data.points.map((p) => <option key={p.id} value={p.id}>{p.name}{p.unit ? ` (${p.unit})` : ""}{p.kind === "channel" ? " · channel" : ""}{p.on ? ` · ${p.on}` : ""}</option>)}
                        </Select></Cell>
                      )}
                      <Cell label="Note" className="lsa-wide"><input aria-label={`Note, line ${i + 1}`} value={x.note} maxLength={200} disabled={disabled} onChange={(e) => patch({ note: e.target.value })} /></Cell>
                    </>
                  )} />
          </Section>

          <Section title="Consumables" headingLevel={4} className="mt-needs-sub">
            <p className="field-help">Used up by the job: grease, test reagents, rags. Cost is for the quantity given.</p>
            <Rows label="Consumable lines" rows={draft.consumables} onRows={(v) => set("consumables", v)} blank={{ name: "", qty: "1", unit: "", cost: "" }} addLabel="+ Add a consumable"
                  render={(x, patch, i) => (
                    <>
                      <Cell label="Consumable" className="lsa-wide"><input aria-label={`Consumable, line ${i + 1}`} placeholder="e.g. Grease" value={x.name} maxLength={200} disabled={disabled} onChange={(e) => patch({ name: e.target.value })} /></Cell>
                      <Cell label="Quantity" className="lsa-num"><input type="number" min="0" step="any" inputMode="decimal" aria-label={`Quantity, line ${i + 1}`} value={x.qty} disabled={disabled} onChange={(e) => patch({ qty: e.target.value })} /></Cell>
                      <Cell label="Unit" className="lsa-num"><input aria-label={`Unit, line ${i + 1}`} placeholder="e.g. litre" value={x.unit} maxLength={20} disabled={disabled} onChange={(e) => patch({ unit: e.target.value })} /></Cell>
                      <Cell label={`Cost (${workspaceCurrency()})`} className="lsa-num"><input type="number" min="0" step="any" inputMode="decimal" aria-label={`Cost, line ${i + 1}`} value={x.cost} disabled={disabled} onChange={(e) => patch({ cost: e.target.value })} /></Cell>
                    </>
                  )} />
          </Section>

          <Section title="Access and downtime" headingLevel={4} className="mt-needs-sub">
            <div className="lsa-grid">
              <Field label="Downtime (h)" optional>
                <TextInput type="number" min="0" step="0.25" inputMode="decimal" value={draft.access.downtime_hours} disabled={disabled} onChange={(e) => set("access", { ...draft.access, downtime_hours: e.target.value })} />
              </Field>
              <Field label="Permits (comma between)" optional>
                <TextInput value={draft.access.permits} placeholder="e.g. Hot work, Confined space" disabled={disabled} onChange={(e) => set("access", { ...draft.access, permits: e.target.value })} />
              </Field>
              <Field label="Isolation" optional>
                <TextInput value={draft.access.isolation} maxLength={200} placeholder="e.g. Lock out the pump starter" disabled={disabled} onChange={(e) => set("access", { ...draft.access, isolation: e.target.value })} />
              </Field>
              <Field label="Access equipment" optional>
                <TextInput value={draft.access.access_equipment} maxLength={200} placeholder="e.g. Scaffold, EWP" disabled={disabled} onChange={(e) => set("access", { ...draft.access, access_equipment: e.target.value })} />
              </Field>
            </div>
          </Section>

          <Section title="Method and instructions" headingLevel={4} className="mt-needs-sub">
            <Field label="Method" optional help="How it's done, in a line: “On site with a test kit”, “Sent to the workshop”.">
              <TextInput value={draft.method} maxLength={500} disabled={disabled} onChange={(e) => set("method", e.target.value)} />
            </Field>
            <Field label="Instructions" optional help="The steps, as they go on its work orders.">
              <TextArea rows={4} maxLength={4000} value={instructions} disabled={disabled} onChange={(e) => setInstructions(e.target.value)} />
            </Field>
          </Section>
        </div>
      )}
    </Section>
  );
}

// Labour (who does it: each trade, how many people, the hours each; and the elapsed time), as the
// task panel's Labour fold-out. Saved with the task through useNeeds, as the rest of its needs.
export function LabourRows({ data, needs, disabled = false }) {
  const { draft, set } = needs;
  const t = data.task;
  return (
    <>
      <Rows label="Labour lines" rows={draft.labour} onRows={(v) => set("labour", v)} blank={{ trade: t.trade || "", people: "1", hours: "" }} addLabel="+ Add labour"
            render={(x, patch, i) => (
              <>
                <Cell label="Trade" className="lsa-wide"><input aria-label={`Trade, line ${i + 1}`} placeholder="e.g. Fitter" value={x.trade} maxLength={200} disabled={disabled} onChange={(e) => patch({ trade: e.target.value })} /></Cell>
                <Cell label="People" className="lsa-num"><input type="number" min="1" step="1" inputMode="numeric" aria-label={`People, line ${i + 1}`} value={x.people} disabled={disabled} onChange={(e) => patch({ people: e.target.value })} /></Cell>
                <Cell label="Hours each" className="lsa-num"><input type="number" min="0" step="0.25" inputMode="decimal" aria-label={`Hours each, line ${i + 1}`} value={x.hours} disabled={disabled} onChange={(e) => patch({ hours: e.target.value })} /></Cell>
              </>
            )} />
      <Field label="Elapsed, start to finish (h)" optional className="lsa-duration">
        <TextInput type="number" min="0" step="0.25" inputMode="decimal" aria-label="Elapsed hours" value={draft.duration_hours} disabled={disabled} onChange={(e) => set("duration_hours", e.target.value)} />
      </Field>
    </>
  );
}

// Parts (the spares it fits each time: from the parts register, or a name typed), as the task
// panel's Parts fold-out. Saved with the task through useNeeds.
export function SparesRows({ data, needs, disabled = false }) {
  const [parts, setParts] = useState(null);
  const { draft, set } = needs;
  const needParts = () => {
    if (parts) return;
    setParts([]);
    listMaintenanceParts().then((d) => setParts(d.parts || [])).catch(() => setParts([]));
  };
  const register = [...(data.parts || []), ...((parts || []).filter((p) => !(data.parts || []).some((q) => q.id === p.id)))];
  const partLabel = (p) => `${p.part_number} ${p.name}`;
  return (
    <>
      <Rows label="Spare lines" rows={draft.spares} onRows={(v) => set("spares", v)} blank={{ part_id: "", name: "", qty: "1", part_number: "" }} addLabel="+ Add a spare"
            render={(x, patch, i) => (
              <>
                <Cell label="Spare" className="lsa-wide"><input list="lsa-parts" aria-label={`Spare, line ${i + 1}`} placeholder="Part number or name"
                       value={x.part_id ? `${x.part_number ? `${x.part_number} ` : ""}${x.name}` : x.name} maxLength={200} disabled={disabled} onFocus={needParts}
                       onChange={(e) => {
                         const hit = register.find((p) => partLabel(p) === e.target.value);
                         patch(hit ? { part_id: hit.id, name: hit.name, part_number: hit.part_number } : { part_id: "", name: e.target.value, part_number: "" });
                       }} /></Cell>
                <Cell label="Quantity" className="lsa-num"><input type="number" min="0" step="1" inputMode="decimal" aria-label={`Quantity, line ${i + 1}`} value={x.qty} disabled={disabled} onChange={(e) => patch({ qty: e.target.value })} /></Cell>
                {x.part_id ? <span className="lib-date">from the register</span> : null}
              </>
            )} />
      <datalist id="lsa-parts">{register.map((p) => <option key={p.id} value={partLabel(p)} />)}</datalist>
    </>
  );
}
