import { Link } from "react-router-dom";
import PublicNav from "../components/PublicNav.jsx";
import PublicFooter from "../components/PublicFooter.jsx";
import { articles } from "../learn.js";

// Public index of the evergreen learn articles.
export default function LearnIndex() {
  return (
    <div className="landing">
      <PublicNav />

      <section className="blog-list">
        <header className="blog-head">
          <div className="landing-eyebrow">Learn</div>
          <h1>Reliability engineering, explained properly</h1>
          <p>
            Practical guides to the methods behind the software — worked
            examples included, no sign-up required.
          </p>
        </header>

        <ul className="blog-posts">
          {articles.map((a) => (
            <li key={a.slug}>
              <Link className="blog-card" to={`/learn/${a.slug}`}>
                <div className="blog-card-meta">
                  <span>{a.readingMinutes} min read</span>
                </div>
                <h2>{a.title}</h2>
                <p>{a.description}</p>
                <span className="blog-more">Read the guide →</span>
              </Link>
            </li>
          ))}
        </ul>
      </section>

      <PublicFooter />
    </div>
  );
}
