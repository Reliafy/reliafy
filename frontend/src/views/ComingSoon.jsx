// Placeholder view for features that aren't built yet.
export default function ComingSoon({ title, subtitle, description }) {
  return (
    <div className="app">
      <header>
        <div>
          <h1>{title}</h1>
          {subtitle && <p>{subtitle}</p>}
        </div>
      </header>
      <div className="card empty">
        <span className="soon-badge">Coming soon</span>
        <h2>{title} aren’t available yet</h2>
        <p>{description}</p>
      </div>
    </div>
  );
}
