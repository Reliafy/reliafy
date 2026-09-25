import { Link } from "react-router-dom";
import PublicNav from "../components/PublicNav.jsx";
import PublicFooter from "../components/PublicFooter.jsx";
import { updates, formatDate } from "../updates.js";

// Public "What's new" index: product updates, newest first. Same layout as the
// blog list (and the same content as the monthly product-update email).
export default function WhatsNew() {
  return (
    <div className="landing">
      <PublicNav />

      <section className="blog-list">
        <header className="blog-head">
          <div className="landing-eyebrow">What's new</div>
          <h1>Product updates</h1>
          <p>
            What's changed in Reliafy, roughly monthly. For explainers of the
            methods themselves, <Link to="/blog">see the blog</Link>.
          </p>
        </header>

        {updates.length === 0 ? (
          <p className="blog-empty">Nothing here yet — check back soon.</p>
        ) : (
          <ul className="blog-posts">
            {updates.map((u) => (
              <li key={u.slug}>
                <Link className="blog-card" to={`/whats-new/${u.slug}`}>
                  <div className="blog-card-meta">
                    <time>{formatDate(u.date)}</time>
                  </div>
                  <h2>{u.title}</h2>
                  <p>{u.summary}</p>
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
