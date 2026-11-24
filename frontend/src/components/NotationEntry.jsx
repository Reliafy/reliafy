import { useEffect, useRef, useState } from "react";
import Field from "./ui/Field.jsx";
import Units from "./Units.jsx";
import PreviewTable from "./PreviewTable.jsx";
import Loading from "./ui/Loading.jsx";
import LifetimesView from "./LifetimesView.jsx";
import { readNotation } from "../api.js";
import {
  NOTATION_HINT, NOTATION_PLACEHOLDER, NOTATION_RULES, createNotationReader, readingView,
} from "../notationReading.js";

// The live reading of typed text: what the server (SurPyval) read it as, a
// short pause after each change. Answers readingView's object.
export function useNotationReading(text) {
  const [answer, setAnswer] = useState(null);
  const reader = useRef(null);
  if (!reader.current) reader.current = createNotationReader((t, opts) => readNotation(t, null, { ...opts, lifetimes: true }), setAnswer);
  useEffect(() => { reader.current.read(text); }, [text]);
  useEffect(() => () => reader.current.stop(), []);
  return readingView(text, answer);
}

// New dataset's "Type it in": lives typed as text in SurPyval's notation
// ("120, 310, [400, 450], 1000+"), with what can be typed folded under the
// box, the unit (required, as for an upload), and the live reading: what was
// understood and the columns it will be saved with, or where it stopped.
export default function NotationEntry({ text, onText, unit, onUnit, view, disabled }) {
  const [lastLifetimes, setLastLifetimes] = useState(null);
  useEffect(() => {
    if (view.state === "ok") setLastLifetimes(view.lifetimes || null);
    else if (view.state === "empty") setLastLifetimes(null);
  }, [view.state, view.lifetimes]);
  return (
    <div className="ds-notation">
      <Field label="Lives" help={NOTATION_HINT} error={view.state === "error" ? view.error : null}>
        <textarea className="paste-area ds-notation-text" value={text} spellCheck={false} disabled={disabled}
                  placeholder={NOTATION_PLACEHOLDER} onChange={(e) => onText(e.target.value)} />
      </Field>
      <details className="ds-more">
        <summary>What can I type?</summary>
        <div className="ds-more-body">
          <p className="hint m-0">
            Separate the lives with commas, or put each on its own line. Times are in the unit below.
          </p>
          <dl className="ds-notation-rules">
            {NOTATION_RULES.map((r) => (
              <div key={r.write} className="ds-notation-rule">
                <dt><code>{r.write}</code></dt>
                <dd>{r.means}</dd>
              </div>
            ))}
          </dl>
          <p className="hint m-0">
            For example <code>120, 310, [400, 450], 1000+</code> is four units: two failed, one between 400 and
            450, one still running at 1000.
          </p>
        </div>
      </details>
      <Units value={unit} onChange={onUnit} listId="notation-units" />
      {view.state === "reading" && <Loading inline as="p" label="Reading…" />}
      {view.state === "ok" && (
        <section className="ds-notation-read" aria-label="What was read">
          <p className="ds-notation-summary m-0" role="status">
            Read as: <strong>{view.summary}</strong>
          </p>
          <div className="ds-section-h">
            Saved as {view.nRows} row{view.nRows === 1 ? "" : "s"} · columns {view.columns.join(", ")}
          </div>
          <PreviewTable columns={view.columns} rows={view.rows} />
        </section>
      )}
      {/* The lifetimes as the dataset's page will draw them, redrawn as you type (the last good reading stays
          while the text can't be read). */}
      {lastLifetimes && <LifetimesView data={lastLifetimes} name="New dataset" />}
    </div>
  );
}
