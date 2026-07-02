import { Link } from "react-router-dom";
import PublicNav from "../components/PublicNav.jsx";
import { posts, formatDate } from "../blog.js";

// Public blog index: a list of posts, newest first.
export default function Blog() {
  return (
    <div className="landing">
      <PublicNav />

      <section className="blog-list">
        <header className="blog-head">
          <div className="landing-eyebrow">Blog</div>
          <h1>Notes on reliability engineering</h1>
          <p>Product updates and practical notes from the Reliafy team.</p>
        </header>

        {posts.length === 0 ? (
          <p className="blog-empty">No posts yet — check back soon.</p>
        ) : (
          <ul className="blog-posts">
            {posts.map((p) => (
              <li key={p.slug}>
                <Link className="blog-card" to={`/blog/${p.slug}`}>
                  <div className="blog-card-meta">
                    <time>{formatDate(p.date)}</time>
                    <span className="blog-dot">·</span>
                    <span>{p.readingMinutes} min read</span>
                  </div>
                  <h2>{p.title}</h2>
                  <p>{p.summary}</p>
                  <span className="blog-more">Read more →</span>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </section>

      <footer className="landing-foot">
        <span>© Reliafy</span>
      </footer>
    </div>
  );
}
