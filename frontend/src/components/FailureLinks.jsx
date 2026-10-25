import { useId, useMemo, useRef, useState } from "react";
import Modal from "./Modal.jsx";
import { saveErrorText } from "../confirm.js";
import { filterChoices, linkChoices } from "../explorerRcm.js";
import { FUNCTION_MAX } from "../rcmWorksheet.js";
import "./FailureLinks.css";

// A functional failure caused by lower ones, in the Explorer's RCM tab: the
// two sections of its details panel (Caused by, on positions below; Causes, on
// positions above) and the picker that links failures from either end. The
// panel's two sections are self-contained blocks, so they can sit beside the
// function panel's own without the two meeting.

const plural = (count, one, many = `${one}s`) => `${count.toLocaleString("en-AU")} ${count === 1 ? one : many}`;
const shorter = (t, n = 70) => (t.length > n ? `${t.slice(0, n - 1)}…` : t);

// "Caused by, on positions below": the lower failures that cause this one,
// each a link that goes to it, with its position and Unlink; the way to add one.
// `links`: {onLink(r, "cause" | "effect"), onUnlink(effectId, causeId)}.
export function CausedBySection({ r, where, readOnly, links, onSelect }) {
  const causes = r.ref.causes || [];
  const b = r.ref.below;
  const own = r.sum.modes > 0;
  const summary = [
    plural(causes.length, "cause"),
    b?.modes ? `${plural(b.modes, "failure mode")} below` : null,
    b?.modes ? (b.undecided ? `${b.undecided.toLocaleString("en-AU")} to decide` : "all decided") : null,
  ].filter(Boolean).join(" · ");
  return (
    <section className="fl-sec" aria-label="Caused by, on positions below">
      <h3>Caused by, on positions below</h3>
      {causes.length > 0 && <p className="fl-sum">{summary}</p>}
      {r.ref.explained_below && !own && (
        <p className="fl-note">
          Explained below: the failure-mode questions for this failure are answered on the positions linked.
          Add failure modes here only for causes that belong to {where || "this position"} itself.
        </p>
      )}
      {causes.length === 0 && <p className="fl-sum">Nothing linked yet. A failure on a position inside {where || "this one"} can be its cause.</p>}
      <ul className="fl-list">
        {causes.map((c) => (
          <li key={c.id}>
            <span className="fl-main">
              <button type="button" className="link fl-go" onClick={() => onSelect(c.id)} title={`${c.text}: go to it`}>{c.text}</button>
              <span className="fl-on">on {c.position?.name}</span>
              {c.inside === false ? (
                <span className="fl-warn">Not inside {where || "it"} any more, so it doesn&apos;t count.</span>
              ) : !c.covered && <span className="rw-todo fl-chip">{c.chain?.undecided ? `${c.chain.undecided} to decide` : "not finished"}</span>}
            </span>
            {!readOnly && <button type="button" className="link fl-unlink" onClick={() => links.onUnlink(r.ref.id, c.id)}
                                  aria-label={`Unlink ${c.text}`}>Unlink</button>}
          </li>
        ))}
      </ul>
      {!readOnly && (
        <button type="button" className="secondary fl-add" onClick={(e) => { if (e.detail < 2) links.onLink(r, "cause"); }}>Link to a cause…</button>
      )}
    </section>
  );
}

// "Causes, on positions above": the failures above that this one causes.
export function CausesSection({ r, where, readOnly, links, onSelect }) {
  const effects = r.ref.effects || [];
  const canUp = !!r.ref.has_above;
  return (
    <section className="fl-sec" aria-label="Causes, on positions above">
      <h3>Causes, on positions above</h3>
      {effects.length === 0 && (
        <p className="fl-sum">{canUp ? `Not linked to a failure above ${where || "it"} yet.` : "Nothing above: this failure is the top of its chain."}</p>
      )}
      <ul className="fl-list">
        {effects.map((e) => (
          <li key={e.id}>
            <span className="fl-main">
              <button type="button" className="link fl-go" onClick={() => onSelect(e.id)} title={`${e.text}: go to it`}>{e.text}</button>
              <span className="fl-on">on {e.position?.name}</span>
              {e.inside === false && <span className="fl-warn">{where || "This position"} isn&apos;t inside it any more, so it doesn&apos;t count.</span>}
            </span>
            {!readOnly && <button type="button" className="link fl-unlink" onClick={() => links.onUnlink(e.id, r.ref.id)}
                                  aria-label={`Unlink ${e.text}`}>Unlink</button>}
          </li>
        ))}
      </ul>
      {!readOnly && canUp && (
        <button type="button" className="secondary fl-add" onClick={(e) => { if (e.detail < 2) links.onLink(r, "effect"); }}>Link to an effect…</button>
      )}
    </section>
  );
}

// The picker. `direction` "cause": tick the failures on positions inside the
// failure's own that cause it; "effect": tick the failures on positions above
// that it causes. Grouped by position, with a filter box. Failures not written
// yet are added from the foot ("New functional failure on a position …") and
// written, with their function, when Link is pressed. `onLink(items, made)`
// writes them (useTreeRcm's linkMany) and resolves once the RCM is read again;
// until then the dialog says "Linking…" and sends nothing more, and a refusal
// shows in it with the ticks kept.
export default function LinkFailurePicker({ direction, row, whole, onLink, onClose }) {
  const up = direction === "effect";
  const id = useId();
  const groups = useMemo(() => linkChoices(whole, row.key, direction), [whole, row.key, direction]);
  const [query, setQuery] = useState("");
  const [ticked, setTicked] = useState(() => new Set());
  const [made, setMade] = useState([]); // failures to write: {id, position_id, position, function_id, function_text, text}
  const [form, setForm] = useState(null); // the "New functional failure…" form
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const list = useRef(null);
  const filterBox = useRef(null);
  const sent = useRef(false);
  const memo = useRef({}); // what was written already, if a refusal means trying again
  const shown = filterChoices(groups, query);
  const word = up ? "effect" : "cause";
  const count = [...ticked].filter((k) => !made.some((m) => m.id === k)).length + made.length;
  const place = up ? "above" : "below";
  const where = row.ref.position_name || whole.rows.get(row.ref.position_id)?.ref.name || "this position";

  const tick = (key, on) => setTicked((s) => {
    const next = new Set(s);
    if (on) next.add(key);
    else next.delete(key);
    return next;
  });

  const submit = async () => {
    if (!count || sent.current) return;
    sent.current = true;
    setBusy(true);
    setError(null);
    const here = row.key;
    const items = [
      ...[...ticked].filter((k) => !made.some((m) => m.id === k)).map((k) => (up ? { effect: k, cause: here } : { effect: here, cause: k })),
      ...made.map((m) => ({ id: m.id, effect: up ? undefined : here, cause: up ? here : undefined,
        make: { position_id: m.position_id, function_id: m.function_id, function_text: m.function_text, text: m.text } })),
    ];
    try {
      await onLink(items, memo.current);
      onClose(count);
    } catch (e) {
      sent.current = false;
      setBusy(false);
      setError(saveErrorText(e, { what: "link them", offline: navigator.onLine === false }));
    }
  };

  const boxes = () => [...(list.current?.querySelectorAll("input[type=checkbox]:not(:disabled)") || [])];
  const onKeyDown = (e) => {
    if (e.target.closest(".fl-new")) return;
    if (e.key === "Enter" && !e.target.closest("button, textarea, select")) {
      e.preventDefault();
      submit();
    } else if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      const all = e.target === filterBox.current ? [filterBox.current, ...boxes()] : [filterBox.current, ...boxes()];
      const at = all.indexOf(e.target);
      if (at < 0) return;
      e.preventDefault();
      all[Math.max(0, Math.min(all.length - 1, at + (e.key === "ArrowDown" ? 1 : -1)))]?.focus();
    }
  };

  const openForm = (positionId) => {
    const g = groups.find((x) => x.id === positionId) || groups[0];
    if (!g) return;
    setForm({ position_id: g.id, function_id: g.functions[0]?.id || "", function_text: "", text: "" });
  };
  const formGroup = form && groups.find((g) => g.id === form.position_id);
  const newFunction = form && (!form.function_id || !formGroup?.functions.some((f) => f.id === form.function_id));
  const formOk = form && form.text.trim() && (!newFunction || form.function_text.trim());
  const addNew = () => {
    if (!formOk) return;
    const fn = formGroup.functions.find((f) => f.id === form.function_id);
    const entry = {
      id: `new:${made.length + 1}:${form.text.trim()}`, position_id: form.position_id, position: formGroup.name,
      function_id: newFunction ? null : form.function_id, function_text: newFunction ? form.function_text.trim() : fn.text,
      text: form.text.trim(),
    };
    setMade((m) => [...m, entry]);
    tick(entry.id, true);
    setForm(null);
  };
  const drop = (key) => {
    setMade((m) => m.filter((x) => x.id !== key));
    tick(key, false);
  };

  return (
    <Modal title={`Link ${up ? "an effect" : "a cause"} of “${shorter(row.ref.text || "this functional failure")}”`} onClose={() => onClose(0)} locked={busy}
           className="link-picker"
           footer={(
             <>
               <span className="lp-keys">↑↓ move · Space ticks · Enter links</span>
               <div className="lp-foot">
                 {error && <p className="lp-error" role="alert" id={`${id}-err`}>{error}</p>}
                 <button type="button" className="secondary" onClick={() => onClose(0)} disabled={busy}>Cancel</button>
                 <button type="button" onClick={submit} disabled={!count || busy} aria-busy={busy || undefined}
                         aria-describedby={error ? `${id}-err` : undefined}>
                   {busy ? "Linking…" : count ? `Link ${plural(count, word)}` : "Link"}
                 </button>
               </div>
             </>
           )}>
      <div onKeyDown={onKeyDown}>
        <p className="lp-sub">
          {up
            ? `Functional failures on positions above ${where}. Tick the ones it causes.`
            : `Functional failures on positions inside ${where}. Tick the ones that cause it.`}
        </p>
        <input ref={filterBox} type="search" className="lp-filter" value={query} onChange={(e) => setQuery(e.target.value)}
               placeholder="Filter: position, function or failure" aria-label="Filter the list" autoFocus />
        <div className="lp-list" ref={list} role="group" aria-label={`Functional failures ${place}`}>
          {shown.map((g) => (
            <div key={g.id} className="lp-group">
              <h4 className="lp-pos" style={{ paddingLeft: 12 + g.depth * 14 }}>{g.name}</h4>
              {g.items.map((it) => (
                <label key={it.id} className={"lp-item" + (it.linked ? " linked" : "")} style={{ paddingLeft: 12 + g.depth * 14 }}>
                  <input type="checkbox" checked={it.linked || ticked.has(it.id)} disabled={it.linked || busy}
                         onChange={(e) => tick(it.id, e.target.checked)} />
                  <span className="lp-t"><span className="lp-fn">{shorter(it.function, 40)} ›</span> {it.text}</span>
                  <span className="lp-s">{it.linked ? "linked" : it.summary}</span>
                </label>
              ))}
            </div>
          ))}
          {!query && groups.filter((g) => g.items.length === 0).map((g) => (
            <div key={g.id} className="lp-group">
              <h4 className="lp-pos" style={{ paddingLeft: 12 + g.depth * 14 }}>{g.name}</h4>
              <p className="lp-none" style={{ paddingLeft: 12 + g.depth * 14 }}>
                No functional failures yet · <button type="button" className="link" onClick={() => openForm(g.id)} disabled={busy}>New…</button>
              </p>
            </div>
          ))}
          {made.length > 0 && (
            <div className="lp-group">
              <h4 className="lp-pos">To be written</h4>
              {made.map((m) => (
                <label key={m.id} className="lp-item">
                  <input type="checkbox" checked={ticked.has(m.id)} disabled={busy} onChange={(e) => tick(m.id, e.target.checked)} />
                  <span className="lp-t"><span className="lp-fn">{m.position} › {shorter(m.function_text, 40)} ›</span> {m.text}</span>
                  <span className="lp-s">new <button type="button" className="link" onClick={(e) => { e.preventDefault(); drop(m.id); }}
                                                      disabled={busy} aria-label={`Don't add ${m.text}`}>Remove</button></span>
                </label>
              ))}
            </div>
          )}
          {!groups.length && (
            <p className="lp-none lp-empty">{up ? "There is no position above this one." : `There are no positions inside ${where} yet.`}</p>
          )}
          {groups.length > 0 && query && !shown.length && <p className="lp-none lp-empty">Nothing matches “{query}”.</p>}
        </div>
        {groups.length > 0 && (form ? (
          <div className="fl-new" role="group" aria-label={`New functional failure on a position ${place}`}
               onKeyDown={(e) => {
                 if (e.key === "Enter" && !e.target.closest("button")) { e.preventDefault(); e.stopPropagation(); addNew(); }
                 if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); setForm(null); }
               }}>
            <h4>New functional failure on a position {place}</h4>
            <label className="fl-f"><span>Position</span>
              <select value={form.position_id} disabled={busy}
                      onChange={(e) => setForm({ ...form, position_id: e.target.value,
                        function_id: groups.find((g) => g.id === e.target.value)?.functions[0]?.id || "" })}>
                {groups.map((g) => <option key={g.id} value={g.id}>{g.name}</option>)}
              </select>
            </label>
            <label className="fl-f"><span>Function</span>
              <select value={newFunction ? "" : form.function_id} disabled={busy}
                      onChange={(e) => setForm({ ...form, function_id: e.target.value })}>
                {formGroup?.functions.map((f) => <option key={f.id} value={f.id}>{shorter(f.text, 60)}</option>)}
                <option value="">New function…</option>
              </select>
            </label>
            {newFunction && (
              <label className="fl-f"><span>What must it do?</span>
                <input type="text" value={form.function_text} maxLength={FUNCTION_MAX} disabled={busy}
                       onChange={(e) => setForm({ ...form, function_text: e.target.value })} autoFocus />
              </label>
            )}
            <label className="fl-f"><span>How does it fail to do it?</span>
              <input type="text" value={form.text} disabled={busy} onChange={(e) => setForm({ ...form, text: e.target.value })}
                     autoFocus={!newFunction} />
            </label>
            <div className="fl-new-acts">
              <button type="button" className="secondary" onClick={() => setForm(null)} disabled={busy}>Cancel</button>
              <button type="button" onClick={addNew} disabled={!formOk || busy}>Add to the list</button>
            </div>
            <p className="lp-sub">It is written, with its function, when you press Link.</p>
          </div>
        ) : (
          <div className="lp-newrow">
            <button type="button" className="link lp-newbtn" onClick={() => openForm(shown[0]?.id || groups[0].id)} disabled={busy}>
              New functional failure on a position {place}…
            </button>
          </div>
        ))}
      </div>
    </Modal>
  );
}
