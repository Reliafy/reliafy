import { Link, useParams } from "react-router-dom";
import PublicNav from "../components/PublicNav.jsx";
import { getPost, renderMarkdown, formatDate } from "../blog.js";

// Public single-post page. Renders the Markdown body to HTML (content is
// authored in-repo, so it's trusted).
export default function BlogPost() {
  const { slug } = useParams();
  const post = getPost(slug);

  if (!post) {
    return (
      <div className="landing">
        <PublicNav />
        <section className="blog-article">
          <h1>Post not found</h1>
          <p>This post doesn't exist or may have been moved.</p>
          <Link className="cta cta-ghost" to="/blog">← Back to the blog</Link>
        </section>
      </div>
    );
  }

  return (
    <div className="landing">
      <PublicNav />

      <article className="blog-article">
        <Link className="blog-back" to="/blog">← Blog</Link>
        <header className="blog-article-head">
          <div className="blog-card-meta">
            <time>{formatDate(post.date)}</time>
            <span className="blog-dot">·</span>
            <span>{post.readingMinutes} min read</span>
            {post.author && (
              <>
                <span className="blog-dot">·</span>
                <span>{post.author}</span>
              </>
            )}
          </div>
          <h1>{post.title}</h1>
        </header>

        <div
          className="blog-prose"
          dangerouslySetInnerHTML={{ __html: renderMarkdown(post.body) }}
        />

        <footer className="blog-article-foot">
          <Link className="cta cta-ghost" to="/blog">← Back to the blog</Link>
        </footer>
      </article>

      <footer className="landing-foot">
        <span>© Reliafy</span>
      </footer>
    </div>
  );
}
