import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import Logo from "../components/Logo.jsx";
import { useAuth } from "../AuthProvider.jsx";
import { AUTH_DISABLED } from "../firebase.js";
import { getLibrary } from "../api.js";
import { EntryList, LibraryAbout, LibraryChips, useRobots } from "../components/LibraryEntries.jsx";
import { countsText, libraryPath } from "../libraries.js";
import "./PublicPage.css";
import "./LibraryPages.css";

// A public library as anyone sees it, signed out (and the owner's "Preview as public", ?as=public):
// like a share page (/p/:token), a slim logo bar, "Create free account" when signed out, then the
// library. No menu, no footer. Use buttons ask to sign in. Kept out of search unless the library
// is indexable.
export default function PublicLibraryPage({ id, preview = false }) {
  const { user, loading } = useAuth();
  const [lib, setLib] = useState(null);
  const [error, setError] = useState(null);
  useEffect(() => {
    let live = true;
    setLib(null);
    setError(null);
    getLibrary(id).then((x) => live && setLib(x), (e) => live && setError(e.status === 404
      ? "This library isn’t public, or the link is mistyped."
      : e.message));
    return () => { live = false; };
  }, [id]);
  useRobots(!!lib?.indexable && !preview);
  useEffect(() => {
    if (!lib?.name) return undefined;
    const previous = document.title;
    document.title = `${lib.name} — Library · Reliafy`;
    return () => { document.title = previous; };
  }, [lib?.name]);
  return (
    <div className="landing public-page">
      <header className="landing-nav share-bar">
        <Link className="brand" to="/">
          <Logo size={26} />
          <span className="brand-name">Reliafy</span>
        </Link>
        {/* Only once auth has settled, so a signed-in viewer never sees it flash. */}
        {!AUTH_DISABLED && !loading && !user && (
          <Link className="cta cta-solid" to="/login?signup">Create free account</Link>
        )}
      </header>
      <main className="public-artifact">
        <div className="public-app app">
          {preview && user && (
            <p className="card note lib-preview-note" role="status">
              This is how the library looks to anyone signed out. <Link to={libraryPath(id)}>Back to the library</Link>
            </p>
          )}
          {error && (
            <div className="card empty" style={{ margin: "3rem auto", maxWidth: 520 }}>
              <h2>Library unavailable</h2>
              <p>{error}</p>
            </div>
          )}
          {!error && !lib && <div className="card empty" style={{ margin: "3rem auto", maxWidth: 520 }}>Loading…</div>}
          {lib && (
            <>
              <header className="page-header">
                <div className="ph-main">
                  <div className="title-row"><h1>{lib.name}</h1><LibraryChips lib={lib} /></div>
                  <div className="ph-meta">{[lib.description, countsText(lib)].filter(Boolean).join(" · ")}</div>
                </div>
              </header>
              <LibraryAbout lib={lib} />
              <section className="card" aria-labelledby="lib-entries-h">
                <h2 id="lib-entries-h" className="lib-h">Entries</h2>
                {lib.builtin ? (
                  <p className="lib-quiet">
                    {countsText(lib)}, each cited. <Link to={`/login?next=${encodeURIComponent(libraryPath(lib.id))}`}>Sign in</Link> to
                    browse them and use one as a model.
                  </p>
                ) : <EntryList libraryId={lib.id} entries={lib.entries || []} signedIn={false} />}
              </section>
            </>
          )}
        </div>
      </main>
    </div>
  );
}
