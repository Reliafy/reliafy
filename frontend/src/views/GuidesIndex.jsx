import { useState } from "react";
import { Link } from "react-router-dom";
import PublicNav from "../components/PublicNav.jsx";
import PublicFooter from "../components/PublicFooter.jsx";
import ListSearch from "../components/ListSearch.jsx";
import { guidesByCategory } from "../guides.js";
import { filterGuideGroups } from "../guideFilter.js";

// Public index of the task-oriented product guides, grouped by category, with the same
// filter box as the in-app Guides drawer (guideFilter.js).
export default function GuidesIndex() {
  const [query, setQuery] = useState("");
  const groups = filterGuideGroups(guidesByCategory(), query);
  return (
    <div className="landing">
      <PublicNav />

      <section className="blog-list">
        <header className="blog-head">
          <div className="landing-eyebrow">Guides</div>
          <h1>How to do it in Reliafy</h1>
          <p>
            Step-by-step walkthroughs — do a real task in the app, with a
            screenshot for every step.
          </p>
        </header>

        <div className="tablebar guides-filter">
          <ListSearch value={query} onChange={setQuery} placeholder="Filter guides…" />
        </div>
        {groups.length === 0 && (
          <p className="guides-none" role="status">No guide matches “{query.trim()}”. Try fewer words.</p>
        )}

        {groups.map((group) => (
          <div className="guide-group" key={group.category}>
            <h2 className="guide-group-h">{group.category}</h2>
            <ul className="blog-posts">
              {group.items.map((g) => (
                <li key={g.slug}>
                  <Link className="blog-card" to={`/guides/${g.slug}`}>
                    <div className="blog-card-meta">
                      <span>{g.minutes} min read</span>
                    </div>
                    <h3>{g.title}</h3>
                    <p>{g.task}</p>
                    <span className="blog-more">Open guide →</span>
                  </Link>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </section>

      <PublicFooter />
    </div>
  );
}
