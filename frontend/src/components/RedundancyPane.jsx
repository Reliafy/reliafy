import { useEffect, useState } from "react";
import { createRedundancyGroup, getRedundancyInside, retireRedundancyGroup, updateRedundancyGroup } from "../api.js";
import { saveErrorText } from "../confirm.js";
import { STANDBY_KINDS, blankDraft, draftBody, draftFrom, draftProblems, setWords } from "../redundancy.js";
import { useConfirm } from "./ConfirmProvider.jsx";
import TablePane from "./TablePane.jsx";
import "./RedundancyPane.css";

// Redundancy inside a position, in the Explorer's table area beside the tree (Derryn, 12 Nov 2026;
// no modal): the positions inside it that back each other up, as sets. Each set is either "any k of
// them can do the job" (all running) or duty and standby (the others wait: cold, warm or hot, with
// the chance a waiting one starts, and how fast a warm one ages). Build from what's inside wires
// them as redundancy; a diagram still in series is rewired by Rebuild. Saved as events
// (group.created / updated / member_added / member_removed / standby_set / retired).
//
//   position {id, name}    phone, headingRef, onClose, onDirty: TablePane's
//   onChanged(text)        a set was saved or removed (the tree's badges are read again)
//   onRebuild              where the position has a built RBD: rebuild it with the sets (else null)
//   readOnly               the reason it can't be changed (view only), or null

export default function RedundancyPane({ position, phone = false, headingRef = null, onClose, onDirty, onChanged,
  onRebuild = null, readOnly = null }) {
  const confirm = useConfirm();
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [draft, setDraft] = useState(null);
  const [saving, setSaving] = useState(false);
  const [failed, setFailed] = useState(null);
  const [n, setN] = useState(0);

  useEffect(() => {
    getRedundancyInside(position.id).then((d) => {
      setData(d);
      // Nothing marked yet: the form is open, so the first set is a few ticks away.
      if (!d.sets.length && !readOnly) setDraft((x) => x || blankDraft());
    }, (e) => setError(e));
  }, [position.id, n]); // eslint-disable-line react-hooks/exhaustive-deps

  const edit = (d) => {
    setDraft(d);
    setFailed(null);
    onDirty?.(!!d);
  };
  const was = draft?.id ? data?.sets.find((s) => s.id === draft.id) : null;
  const problems = draft ? draftProblems(draft) : [];
  const save = async () => {
    setSaving(true);
    setFailed(null);
    try {
      const made = was ? await updateRedundancyGroup(was.id, draftBody(draft, was))
        : await createRedundancyGroup(draftBody(draft));
      edit(null);
      setN((x) => x + 1);
      onChanged?.(`${was ? "Saved" : "Marked"} ${made.name}: ${setWords(made)}.`);
    } catch (e) {
      setFailed(saveErrorText(e, { offline: navigator.onLine === false }));
    } finally {
      setSaving(false);
    }
  };
  const remove = async (set) => {
    const ok = await confirm({ title: `Remove the set ${set.name}?`, body: "Its positions stop backing each other up in RBDs " +
      "built from the tree from now on. The set stays in the history.", confirmLabel: "Remove the set" });
    if (!ok) return;
    try {
      await retireRedundancyGroup(set.id);
      if (draft?.id === set.id) edit(null);
      setN((x) => x + 1);
      onChanged?.(`Removed the set ${set.name}.`);
    } catch (e) {
      setFailed(saveErrorText(e, { offline: navigator.onLine === false }));
    }
  };

  const kids = data?.children || [];
  const inOther = (c) => c.set_id && c.set_id !== draft?.id;
  const setName = (id) => data?.sets.find((s) => s.id === id)?.name || "another set";
  const toggle = (id) => {
    const members = draft.members.includes(id) ? draft.members.filter((x) => x !== id) : [...draft.members, id];
    edit({ ...draft, members, k: Math.min(Number(draft.k) || 1, Math.max(members.length - 1, 1)) });
  };
  const set = (key) => (e) => edit({ ...draft, [key]: e.target.value });

  return (
    <TablePane title="Redundancy" subject={position.name} phone={phone} busy={saving} headingRef={headingRef}
               onClose={onClose} className="redundancy-pane">
      <div className="redundancy">
        <p className="rim-tquiet redundancy-intro">
          Mark the positions inside {position.name} that back each other up. An RBD built from what&apos;s inside wires
          each set as redundancy (any k of n, or duty and standby), never in series.
        </p>
        {error && <p className="field-error" role="alert">The positions inside didn&apos;t load: {error.message}</p>}
        {!data && !error && <p className="rim-tquiet">Reading the positions inside…</p>}
        {data && kids.length < 2 && (
          <p className="rim-tquiet">{position.name} has {kids.length ? "one position" : "no positions"} inside: a set needs two or more.</p>
        )}
        {data && data.sets.length > 0 && (
          <ul className="redundancy-sets" aria-label="Redundancy sets">
            {data.sets.map((s) => (
              <li key={s.id} className={"redundancy-set" + (draft?.id === s.id ? " is-editing" : "")}>
                <div className="redundancy-set-main">
                  <b className="redundancy-set-name">{s.name}</b>
                  <span className="redundancy-set-how">{setWords(s)}</span>
                  <span className="rim-tquiet redundancy-set-members">{s.members.map((m) => m.name).join(" · ")}
                    {s.outside?.length ? ` (and ${s.outside.map((m) => m.name).join(", ")}, elsewhere)` : ""}</span>
                </div>
                {!readOnly && (
                  <div className="redundancy-set-tools">
                    <button type="button" className="secondary sm" onClick={() => edit(draftFrom(s))} disabled={saving}>Edit</button>
                    <button type="button" className="ghost sm" onClick={() => remove(s)} disabled={saving}>Remove…</button>
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}
        {data && !draft && !readOnly && kids.length >= 2 && (
          <div className="redundancy-actions">
            <button type="button" className="secondary" onClick={() => edit(blankDraft())}>New set</button>
            {onRebuild && data.sets.length > 0 && (
              <button type="button" className="ghost" onClick={onRebuild}>Rebuild the RBD with these sets…</button>
            )}
          </div>
        )}
        {data && draft && kids.length >= 2 && (
          <section className="redundancy-form" aria-label={was ? `Edit ${was.name}` : "New redundancy set"}>
            <h3 className="redundancy-form-title">{was ? `Edit ${was.name}` : "New set"}</h3>
            <fieldset className="redundancy-members">
              <legend>Which positions back each other up</legend>
              {kids.map((c) => (
                <label key={c.id} className="redundancy-member">
                  <input type="checkbox" checked={draft.members.includes(c.id)} disabled={!!inOther(c)}
                         onChange={() => toggle(c.id)} />
                  <span>{c.name}</span>
                  {inOther(c) && <small className="rim-tquiet">in {setName(c.set_id)}</small>}
                </label>
              ))}
            </fieldset>
            <fieldset className="redundancy-mode">
              <legend>How they back each other up</legend>
              <label className="redundancy-choice">
                <input type="radio" name="redundancy-mode" checked={draft.mode === "active"} onChange={() => edit({ ...draft, mode: "active" })} />
                <span><b>Any of them can do the job</b> · all running at once</span>
              </label>
              <label className="redundancy-choice">
                <input type="radio" name="redundancy-mode" checked={draft.mode === "standby"} onChange={() => edit({ ...draft, mode: "standby" })} />
                <span><b>Duty and standby</b> · the others wait to take over</span>
              </label>
            </fieldset>
            <div className="redundancy-fields">
              <label className="redundancy-field">
                <span>{draft.mode === "standby" ? "Running at once" : "Needed at once"}</span>
                <input type="number" inputMode="numeric" min="1" step="1" max={Math.max(draft.members.length - 1, 1)}
                       value={draft.k} onChange={set("k")} aria-describedby="redundancy-k-help" />
                <small id="redundancy-k-help" className="rim-tquiet">
                  of the {draft.members.length || "ticked"} ({draft.mode === "standby" ? "the rest wait" : "the rest are spare capacity"})
                </small>
              </label>
              {draft.mode === "standby" && (
                <>
                  <label className="redundancy-field">
                    <span>While it waits</span>
                    <select value={draft.standby} onChange={set("standby")}>
                      {STANDBY_KINDS.map((k) => <option key={k.value} value={k.value}>{k.label}</option>)}
                    </select>
                    <small className="rim-tquiet">{STANDBY_KINDS.find((k) => k.value === draft.standby)?.help}</small>
                  </label>
                  {draft.standby === "cold" && (
                    <label className="redundancy-field">
                      <span>Starts when switched in (%)</span>
                      <input inputMode="decimal" value={draft.start} placeholder="100" onChange={set("start")} />
                      <small className="rim-tquiet">The chance a waiting one starts. Blank: it always does.</small>
                    </label>
                  )}
                  {draft.standby === "warm" && (
                    <label className="redundancy-field">
                      <span>Ages while waiting (% of running)</span>
                      <input inputMode="decimal" value={draft.ages} placeholder="needed" onChange={set("ages")} />
                      <small className="rim-tquiet">Blank: the RBD draws the set as any {draft.k} of {draft.members.length || "n"}, taking turns.</small>
                    </label>
                  )}
                </>
              )}
              <label className="redundancy-field">
                <span>Name (optional)</span>
                <input value={draft.name} maxLength={200} placeholder="e.g. Duty / standby pumps" onChange={set("name")} />
              </label>
            </div>
            {problems.length > 0 && draft.members.length > 0 && <p className="rim-tquiet" role="status">{problems[0]}</p>}
            {failed && <p className="field-error" role="alert">{failed}</p>}
            <div className="redundancy-actions">
              <button type="button" className="primary" onClick={save} disabled={saving || problems.length > 0}>
                {saving ? "Saving…" : was ? "Save the set" : "Mark the set"}
              </button>
              <button type="button" className="ghost" onClick={() => edit(null)} disabled={saving}>Cancel</button>
            </div>
          </section>
        )}
        {readOnly && <p className="rim-tquiet">{readOnly}</p>}
      </div>
    </TablePane>
  );
}
