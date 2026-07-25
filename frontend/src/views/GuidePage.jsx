import { Link, useParams } from "react-router-dom";
import PublicNav from "../components/PublicNav.jsx";
import PublicFooter from "../components/PublicFooter.jsx";
import GuideBody from "../components/GuideBody.jsx";
import { getGuide } from "../guides.js";

// One public product guide.
export default function GuidePage() {
  const { slug } = useParams();
  const guide = getGuide(slug);

  if (!guide) {
    return (
      <div className="landing">
        <PublicNav />
        <section className="blog-article">
          <h1>Guide not found</h1>
          <p>This guide doesn't exist or may have been moved.</p>
          <Link className="cta cta-ghost" to="/guides">← All guides</Link>
        </section>
        <PublicFooter />
      </div>
    );
  }

  return (
    <div className="landing">
      <PublicNav />
      <section className="blog-article">
        <Link className="blog-back" to="/guides">← Guides</Link>
        <GuideBody guide={guide} />
        {guide.related && (
          <div className="guide-cta">
            <a className="cta" href={guide.related.href}>{guide.related.label} →</a>
          </div>
        )}
      </section>
      <PublicFooter />
    </div>
  );
}
