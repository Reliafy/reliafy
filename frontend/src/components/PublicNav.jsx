import { Link } from "react-router-dom";
import Logo from "./Logo.jsx";
import { useAuth } from "../AuthProvider.jsx";

// Shared top bar for the public (marketing + blog) pages.
export default function PublicNav() {
  const { user } = useAuth();
  return (
    <header className="landing-nav">
      <Link className="brand" to="/">
        <Logo size={30} />
        <span className="brand-name">Reliafy</span>
      </Link>
      <nav className="landing-nav-actions">
        <Link className="landing-nav-link" to="/#features">Features</Link>
        <Link className="landing-nav-link" to="/#pricing">Pricing</Link>
        <Link className="landing-nav-link" to="/learn">Learn</Link>
        <Link className="landing-nav-link" to="/blog">Blog</Link>
        {user ? (
          <Link className="cta cta-solid" to="/modelling">Open the app</Link>
        ) : (
          <>
            <Link className="cta cta-ghost" to="/login">Sign in</Link>
            <Link className="cta cta-solid" to="/login">Get started</Link>
          </>
        )}
      </nav>
    </header>
  );
}
