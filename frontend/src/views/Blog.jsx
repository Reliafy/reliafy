import { useState } from "react";
import { Link } from "react-router-dom";
import PublicNav from "../components/PublicNav.jsx";
import PublicFooter from "../components/PublicFooter.jsx";
import { posts, formatDate } from "../blog.js";
import { articles } from "../learn.js";

// The single writing index: dated posts and evergreen Learn articles in one
// list, tagged so you can tell them apart, with a filter for each. Learn
// articles keep their own /learn/:slug URLs — those are the indexed pages that
// rank, so only the index is consolidated here.
const FILTERS = [
  { id: "all", label: "Everything" },
  { id: "post", label: "Posts" },
  { id: "learn", label: "Learn" },
];

export default function Blog() {
  const [filter, setFilter] = useState("all");

  const entries = [
    ...posts.map((p) => ({
      kind: "post",
      slug: p.slug,
      href: `/blog/${p.slug}`,
      title: p.title,
      summary: p.summary,
      minutes: p.readingMinutes,
      date: p.date,
    })),
    ...articles.map((a) => ({
      kind: "learn",
      slug: a.slug,
      href: `/learn/${a.slug}`,
      title: a.title,
      summary: a.description,
      minutes: a.readingMinutes,
      date: null,
    })),
  ];

  const shown = filter === "all" ? entries : entries.filter((e) => e.kind === filter);

  return (
    <div className="landing">
      <PublicNav />

      <section className="blog-list">
        <header className="blog-head">
          <div className="landing-eyebrow">Writing</div>
          <h1>Notes on reliability engineering</h1>
          <p>
            Practical explainers of the methods behind the software, plus product
            updates from the Reliafy team. Looking for how to do something in the
            app? <Link to="/guides">See the guides</Link>.
          </p>
        </header>

        <div className="blog-filters">
          {FILTERS.map((f) => (
            <button
              key={f.id}
              className={"blog-filter" + (filter === f.id ? " active" : "")}
              onClick={() => setFilter(f.id)}
            >
              {f.label}
            </button>
          ))}
        </div>

        {shown.length === 0 ? (
          <p className="blog-empty">Nothing here yet — check back soon.</p>
        ) : (
          <ul className="blog-posts">
            {shown.map((e) => (
              <li key={`${e.kind}-${e.slug}`}>
                <Link className="blog-card" to={e.href}>
                  <div className="blog-card-meta">
                    {e.kind === "learn" ? (
                      <span className="blog-tag">Learn</span>
                    ) : (
                      <>
                        <time>{formatDate(e.date)}</time>
                        <span className="blog-dot">·</span>
                      </>
                    )}
                    <span>{e.minutes} min read</span>
                  </div>
                  <h2>{e.title}</h2>
                  <p>{e.summary}</p>
                  <span className="blog-more">Read more →</span>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </section>

      <PublicFooter />
    </div>
  );
}
