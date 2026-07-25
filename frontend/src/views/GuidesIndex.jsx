import { Link } from "react-router-dom";
import PublicNav from "../components/PublicNav.jsx";
import PublicFooter from "../components/PublicFooter.jsx";
import { guidesByCategory } from "../guides.js";

// Public index of the task-oriented product guides, grouped by category.
export default function GuidesIndex() {
  const groups = guidesByCategory();
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

        {groups.map((group) => (
          <div className="guide-group" key={group.category}>
            <h2 className="guide-group-h">{group.category}</h2>
            <ul className="blog-posts">
              {group.items.map((g) => (
                <li key={g.slug}>
                  <Link className="blog-card" to={`/guides/${g.slug}`}>
                    <div className="blog-card-meta">
                      <span>{g.steps} steps</span>
                      <span>· {g.minutes} min</span>
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
