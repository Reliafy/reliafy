import { useEffect } from "react";
import { Link, useParams } from "react-router-dom";
import PublicNav from "../components/PublicNav.jsx";
import PublicFooter from "../components/PublicFooter.jsx";
import ReferenceEntry from "../components/ReferenceEntry.jsx";
import { getFamily, renderMarkdown } from "../reference.js";

// One family of models: the shared intro, then every entry with an anchor of
// its own so the app's contextual "?" links can deep-link to it.
export default function ReferenceFamily() {
  const { family: familyId } = useParams();
  const family = getFamily(familyId);

  // Anchors arrive before React has rendered the sections, so the browser's own
  // scroll-to-hash misses. Do it once the entries exist.
  useEffect(() => {
    if (!family) return;
    const id = decodeURIComponent(window.location.hash.slice(1));
    if (id) document.getElementById(id)?.scrollIntoView({ block: "start" });
  }, [family]);

  if (!family) {
    return (
      <div className="landing">
        <PublicNav />
        <section className="blog-article">
          <h1>Not found</h1>
          <p>There's no model family at this address.</p>
          <Link className="cta cta-ghost" to="/reference">← Model reference</Link>
        </section>
        <PublicFooter />
      </div>
    );
  }

  return (
    <div className="landing">
      <PublicNav />

      <section className="blog-article ref-family">
        <Link className="blog-back" to="/reference">← Model reference</Link>
        <h1>{family.title}</h1>

        {family.intro && (
          <div className="ref-prose ref-intro"
               dangerouslySetInnerHTML={{ __html: renderMarkdown(family.intro) }} />
        )}

        <nav className="ref-toc" aria-label="Models in this family">
          {family.entries.map((e) => (
            <a key={e.id} href={`#${e.id}`}>{e.name}</a>
          ))}
        </nav>

        {family.entries.map((e) => (
          <ReferenceEntry key={e.id} entry={e} headingLevel={2} />
        ))}
      </section>

      <PublicFooter />
    </div>
  );
}
