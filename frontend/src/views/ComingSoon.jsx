import Chip from "../components/ui/Chip.jsx";
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
        <Chip tone="accent" style={{ marginBottom: 16 }}>Coming soon</Chip>
        <h2>{title} aren’t available yet</h2>
        <p>{description}</p>
      </div>
    </div>
  );
}
