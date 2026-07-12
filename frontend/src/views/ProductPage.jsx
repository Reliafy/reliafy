import { Link } from "react-router-dom";
import PublicNav from "../components/PublicNav.jsx";
import PublicFooter from "../components/PublicFooter.jsx";
import { useAuth } from "../AuthProvider.jsx";

// Shared layout for the SEO product pages (content in productPages.jsx).
// Reuses the landing hero/band sections and the blog prose styles.
export default function ProductPage({ page }) {
  const { user } = useAuth();
  const primaryHref = user ? "/modelling" : "/login?signup";

  return (
    <div className="landing">
      <PublicNav />

      <section className="landing-hero">
        <div className="landing-hero-text">
          <div className="landing-eyebrow">{page.eyebrow}</div>
          <h1>{page.h1}</h1>
          <p>{page.lede}</p>
          <div className="landing-cta">
            <Link className="cta cta-solid lg" to={primaryHref}>Get started free</Link>
            <a className="cta cta-ghost lg" href="https://github.com/Reliafy/reliafy" target="_blank" rel="noreferrer">
              View on GitHub
            </a>
          </div>
        </div>
        <div className="landing-hero-viz">{page.hero}</div>
      </section>

      <section className="prod-prose blog-prose">{page.body}</section>

      <section className="landing-band">
        <h2>{page.band.h2}</h2>
        <p>{page.band.p}</p>
        <Link className="cta cta-solid lg" to={primaryHref}>Get started free</Link>
      </section>

      <PublicFooter />
    </div>
  );
}
