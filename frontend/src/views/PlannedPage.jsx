import { Link } from "react-router-dom";
import { SectionHeader } from "../components/SectionPage.jsx";
import { useAppConfig } from "../ConfigProvider.jsx";
import { PLANNED } from "../plannedPages.js";

// A blank page for a menu entry that isn't built yet (plannedPages.js). Where
// the deployment hasn't turned the menu preview on, nobody is sent here, and a
// direct visit says the page isn't available.
export default function PlannedPage({ id }) {
  const page = PLANNED[id];
  const { menu_preview: preview } = useAppConfig();
  if (!preview) {
    return (
      <div className="app">
        <SectionHeader title="Not available yet" purpose="This page isn't available." />
        <p><Link to="/home">Back to Home</Link></p>
      </div>
    );
  }
  return (
    <div className="app">
      <SectionHeader section={page.section} title={page.title} purpose={page.purpose} />
      <div className="card">
        <p><span className="chip">Preview</span> This page is a placeholder so the menu's structure can be tried. Nothing here works yet.</p>
        <p className="muted">What it will hold:</p>
        <ul>
          {page.will.map((w) => <li key={w}>{w}</li>)}
        </ul>
      </div>
    </div>
  );
}
