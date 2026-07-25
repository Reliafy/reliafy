import { boundsLabel, renderMarkdown, supportLabel } from "../reference.js";

// Greek where SurPyval uses a spelled-out name, so the parameter table matches
// the formulas in the prose (and the labels in the app).
const GREEK = {
  alpha: "α", beta: "β", gamma: "γ", mu: "μ", sigma: "σ", lambda: "λ",
  theta: "θ", nu: "ν", tau: "τ", failure_rate: "λ",
};
const symbol = (name) => GREEK[name] || name;

// One reference entry: the generated facts (parameters, support, stresses)
// followed by the hand-written prose. Shared by the /reference family pages and
// the in-app Help drawer, so the two can never drift.
export default function ReferenceEntry({ entry, headingLevel = 3 }) {
  const H = `h${headingLevel}`;
  const params = entry.params || [];
  const support = supportLabel(entry.support);

  return (
    <article className="ref-entry" id={entry.id}>
      <H className="ref-entry-h">
        {entry.name}
        <code className="ref-id">{entry.id}</code>
      </H>

      <dl className="ref-facts">
        {params.length > 0 && (
          <div>
            <dt>Parameters</dt>
            <dd>
              {params.map((p) => (
                <span className="ref-param" key={p.name}>
                  <code>{symbol(p.name)}</code>
                  <span className="ref-bound">{boundsLabel(p)}</span>
                </span>
              ))}
            </dd>
          </div>
        )}
        {entry.coefficients && (
          <div>
            <dt>Coefficients</dt>
            <dd>
              {entry.coefficients.map((c) => (
                <span className="ref-param" key={c}><code>{c}</code></span>
              ))}
            </dd>
          </div>
        )}
        {support && (
          <div>
            <dt>Support</dt>
            <dd>{support}</dd>
          </div>
        )}
        {entry.n_stress && (
          <div>
            <dt>Stresses</dt>
            <dd>{entry.n_stress === 1 ? "One" : "Two"}</dd>
          </div>
        )}
        {entry.ratio_label && (
          <div>
            <dt>Coefficients read as</dt>
            <dd>{entry.ratio_label}</dd>
          </div>
        )}
        {entry.offsetable && (
          <div>
            <dt>Modifiers</dt>
            <dd>Offset (3-parameter)</dd>
          </div>
        )}
      </dl>

      {entry.prose ? (
        <div className="ref-prose" dangerouslySetInnerHTML={{ __html: renderMarkdown(entry.prose) }} />
      ) : (
        entry.summary && <p className="ref-prose">{entry.summary}</p>
      )}
    </article>
  );
}
