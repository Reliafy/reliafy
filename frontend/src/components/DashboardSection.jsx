import { Link } from "react-router-dom";

// A card linking (or acting) into a section's tool/page.
function DashCard({ to, state, onClick, icon, title, body, cta }) {
  const inner = (
    <>
      <span className="dash-card-ic">{icon}</span>
      <div className="dash-card-body">
        <h3>{title}</h3>
        <p>{body}</p>
      </div>
      <span className="dash-card-cta">{cta} →</span>
    </>
  );
  if (to) {
    return (
      <Link className="dash-card" to={to} state={state}>
        {inner}
      </Link>
    );
  }
  return (
    <button type="button" className="dash-card" onClick={onClick}>
      {inner}
    </button>
  );
}

// Section overview page: breadcrumb + title + (optional) stat strip + a grid of
// cards linking to the section's pages/tools. Used by every section's landing.
export default function DashboardSection({ crumb, title, subtitle, headerAction, stats = [], cards = [] }) {
  return (
    <div className="app">
      <header>
        <div>
          <div className="crumb">{crumb}</div>
          <h1>{title}</h1>
          {subtitle && <p>{subtitle}</p>}
        </div>
        {headerAction}
      </header>

      {stats.length > 0 && (
        <div className="stats">
          {stats.map((s) => (
            <div className="stat" key={s.k}>
              <div className="k">{s.k}</div>
              <div className={"v" + (s.sm ? " sm" : "")}>{s.v}</div>
            </div>
          ))}
        </div>
      )}

      <div className="dash-cards">
        {cards.map((c) => (
          <DashCard key={c.title} {...c} />
        ))}
      </div>
    </div>
  );
}
