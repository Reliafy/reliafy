import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import PublicNav from "../components/PublicNav.jsx";
import PublicFooter from "../components/PublicFooter.jsx";
import { families, modifiers, totalEntries } from "../reference.js";

// Every entry flattened once, for the filter box.
const ALL = families.flatMap((f) =>
  f.entries.map((e) => ({
    id: e.id,
    name: e.name,
    family: f.id,
    familyTitle: f.title,
    haystack: `${e.id} ${e.name} ${f.title}`.toLowerCase(),
  }))
);

// Public index of the model reference: the families, plus a filter across all
// entries so you can jump straight to the one you're looking at in the app.
export default function ReferenceIndex() {
  const [q, setQ] = useState("");
  const query = q.trim().toLowerCase();
  const hits = useMemo(
    () => (query ? ALL.filter((e) => e.haystack.includes(query)) : []),
    [query]
  );

  return (
    <div className="landing">
      <PublicNav />

      <section className="blog-list">
        <header className="blog-head">
          <div className="landing-eyebrow">Reference</div>
          <h1>Every model Reliafy fits</h1>
          <p>
            {totalEntries} models across {families.length} families — parameters,
            functional forms, what each is for, and what to watch out for. The
            parameters and bounds here are generated from the code that does the
            fitting, so they match exactly what you'll see in a result.
          </p>
        </header>

        <div className="ref-search">
          <input
            type="search"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Filter models — weibull, cox_ph, arrhenius…"
            aria-label="Filter models"
          />
        </div>

        {query ? (
          <ul className="ref-hits">
            {hits.map((e) => (
              <li key={`${e.family}/${e.id}`}>
                <Link to={`/reference/${e.family}#${e.id}`}>
                  <strong>{e.name}</strong>
                  <code>{e.id}</code>
                  <span className="ref-hit-family">{e.familyTitle}</span>
                </Link>
              </li>
            ))}
            {hits.length === 0 && <li className="ref-empty">No model matches “{q}”.</li>}
          </ul>
        ) : (
          <ul className="blog-posts">
            {families.map((f) => (
              <li key={f.id}>
                <Link className="blog-card" to={`/reference/${f.id}`}>
                  <div className="blog-card-meta">
                    <span>{f.entries.length} models</span>
                  </div>
                  <h3>{f.title}</h3>
                  <p>{f.description}</p>
                  <span className="blog-more">Open reference →</span>
                </Link>
              </li>
            ))}
          </ul>
        )}

        {!query && (
          <div className="guide-group">
            <h2 className="guide-group-h">Modifiers</h2>
            <p className="ref-modifier-intro">
              These aren't models in their own right — they change how a model is
              fitted, and can be combined with the families above.
            </p>
            <ul className="ref-modifiers">
              {modifiers.map((m) => (
                <li key={m.id}>
                  <strong>{m.name}</strong>
                  <span>{m.applies_to}</span>
                </li>
              ))}
            </ul>
          </div>
        )}
      </section>

      <PublicFooter />
    </div>
  );
}
