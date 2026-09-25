import { Link, useParams } from "react-router-dom";
import PublicNav from "../components/PublicNav.jsx";
import PublicFooter from "../components/PublicFooter.jsx";
import { getUpdate, renderMarkdown, formatDate } from "../updates.js";

// Public single-update page. Renders the Markdown body to HTML (content is
// authored in-repo, so it's trusted).
export default function WhatsNewPost() {
  const { slug } = useParams();
  const update = getUpdate(slug);

  if (!update) {
    return (
      <div className="landing">
        <PublicNav />
        <section className="blog-article">
          <h1>Update not found</h1>
          <p>This update doesn't exist or may have been moved.</p>
          <Link className="cta cta-ghost" to="/whats-new">← All updates</Link>
        </section>
      </div>
    );
  }

  return (
    <div className="landing">
      <PublicNav />

      <article className="blog-article">
        <Link className="blog-back" to="/whats-new">← What's new</Link>
        <header className="blog-article-head">
          <div className="blog-card-meta">
            <time>{formatDate(update.date)}</time>
          </div>
          <h1>{update.title}</h1>
        </header>

        <div
          className="blog-prose"
          dangerouslySetInnerHTML={{ __html: renderMarkdown(update.body) }}
        />

        <footer className="blog-article-foot">
          <Link className="cta cta-ghost" to="/whats-new">← All updates</Link>
        </footer>
      </article>

      <PublicFooter />
    </div>
  );
}
