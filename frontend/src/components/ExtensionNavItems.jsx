import { NavLink } from "react-router-dom";
import { mountsIn } from "../extensions.js";
import { useExtensions } from "../ExtensionsProvider.jsx";

// Sidebar entries for the pages optional extensions add (extensions.js), in
// the menu section each one names.
const ExtensionIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <rect x="4" y="4" width="7" height="7" rx="1.5" />
    <rect x="13" y="4" width="7" height="7" rx="1.5" />
    <rect x="4" y="13" width="7" height="7" rx="1.5" />
    <path d="M16.5 13.5v6M13.5 16.5h6" />
  </svg>
);

export default function ExtensionNavItems({ section, collapsed }) {
  const { mounts } = useExtensions();
  return mountsIn(mounts, section).map((m) => (
    <NavLink
      key={`${m.extension}/${m.id}`}
      to={m.path}
      className={({ isActive }) => "side-item" + (isActive ? " active" : "")}
      title={m.title || m.label}
    >
      <span className="side-icon"><ExtensionIcon /></span>
      {!collapsed && <span className="side-label">{m.label}</span>}
    </NavLink>
  ));
}
