import { Link, useParams } from "react-router-dom";
import PublicNav from "../components/PublicNav.jsx";
import PublicFooter from "../components/PublicFooter.jsx";
import { getArticle, renderMarkdown } from "../learn.js";

// One learn article. Ends with a single contextual CTA to the product page
// it supports (from frontmatter) — no popups, no gates.
export default function LearnArticle() {
  const { slug } = useParams();
  const article = getArticle(slug);

  if (!article) {
    return (
      <div className="landing">
        <PublicNav />
        <section className="blog-article">
          <h1>Article not found</h1>
          <p>This guide doesn't exist or may have been moved.</p>
          <Link className="cta cta-ghost" to="/learn">← All guides</Link>
        </section>
        <PublicFooter />
      </div>
    );
  }

  return (
    <div className="landing">
      <PublicNav />

      <article className="blog-article">
        <Link className="blog-back" to="/learn">← Learn</Link>
        <header className="blog-article-head">
          <div className="blog-card-meta">
            <span>{article.readingMinutes} min read</span>
          </div>
          <h1>{article.title}</h1>
        </header>

        <div
          className="blog-prose"
          dangerouslySetInnerHTML={{ __html: renderMarkdown(article.body) }}
        />

        {article.cta && (
          <aside className="learn-cta">
            <p>{article.cta.text}</p>
            <Link className="cta cta-solid" to={article.cta.href}>{article.cta.label}</Link>
          </aside>
        )}

        <footer className="blog-article-foot">
          <Link className="cta cta-ghost" to="/learn">← All guides</Link>
        </footer>
      </article>

      <PublicFooter />
    </div>
  );
}
