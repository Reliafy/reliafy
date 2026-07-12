import { useState } from "react";
import { NavLink, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../AuthProvider.jsx";
import { useAppConfig } from "../ConfigProvider.jsx";
import Modal from "./Modal.jsx";

const SignOutIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M16 17l5-5-5-5M21 12H9M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
  </svg>
);

// Two-letter avatar from a display name or email.
function initials(user) {
  const base = (user?.displayName || user?.email || "?").trim();
  const parts = base.split(/[\s@.]+/).filter(Boolean);
  const letters = parts.length >= 2 ? parts[0][0] + parts[1][0] : base.slice(0, 2);
  return letters.toUpperCase();
}

// Collapsible left navigation — the Instrument "Workspace" rail.
// Icons mirror the Instrument design (1.7px hairline strokes).
const ModellingIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M3 7c3 0 3 10 6 10s3-14 6-14 3 8 6 8" />
  </svg>
);

const RbdIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <rect x="3" y="4" width="6" height="6" rx="1" />
    <rect x="15" y="4" width="6" height="6" rx="1" />
    <rect x="9" y="14" width="6" height="6" rx="1" />
    <path d="M9 7h6M6 10v4M18 10v4" />
  </svg>
);

const StrategyIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <circle cx="12" cy="12" r="8.5" />
    <path d="M12 12l4-2.5M12 12v4.5" />
    <circle cx="12" cy="12" r="1.6" fill="currentColor" stroke="none" />
  </svg>
);

const FleetIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M3 16V7a1 1 0 0 1 1-1h9v10" />
    <path d="M13 9h4l3 3.5V16h-2.5" />
    <circle cx="7.5" cy="17.5" r="1.8" />
    <circle cx="16.5" cy="17.5" r="1.8" />
    <path d="M9.3 17.5h5.4M3 16h2.7" />
  </svg>
);

const RcmSectionIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <rect x="5" y="4" width="14" height="17" rx="2" />
    <path d="M9 4V3h6v1" />
    <path d="m8.5 12 2 2 4-4.5" />
  </svg>
);

const DatasetsIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <ellipse cx="12" cy="6" rx="8" ry="3" />
    <path d="M4 6v12c0 1.7 3.6 3 8 3s8-1.3 8-3V6" />
  </svg>
);

const GuidesIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <circle cx="12" cy="12" r="9" />
    <path d="M9.5 9a2.5 2.5 0 0 1 4 1.5c0 1.5-2 2-2 3M12 17h.01" />
  </svg>
);

const BillingIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <rect x="3" y="5" width="18" height="14" rx="2" />
    <path d="M3 10h18" />
  </svg>
);

// Routed sections highlight via NavLink (some have nested children that appear
// when the section is active).
const ITEMS = [
  {
    to: "/modelling",
    label: "Modelling",
    icon: <ModellingIcon />,
    children: [
      { to: "/modelling/models", label: "Saved models" },
      { to: "/modelling/compare", label: "Model comparison" },
      { to: "/modelling/degradation", label: "Degradation models" },
    ],
  },
  {
    to: "/rbds",
    label: "RBDs",
    icon: <RbdIcon />,
    children: [{ to: "/rbds/list", label: "Saved diagrams" }],
  },
  {
    to: "/strategy",
    label: "Strategy",
    icon: <StrategyIcon />,
    children: [
      { to: "/strategy/replacement", label: "Optimal replacement" },
      { to: "/strategy/compare", label: "Compare two models" },
      { to: "/strategy/failure-finding", label: "Failure finding" },
      { to: "/strategy/analyses", label: "Saved analyses" },
    ],
  },
  {
    to: "/fleet",
    label: "Fleet",
    icon: <FleetIcon />,
    children: [
      { to: "/fleet/tracking", label: "Degradation tracking" },
      { to: "/fleet/forecasts", label: "Failure forecasts" },
    ],
  },
  {
    to: "/rcm",
    label: "RCM",
    icon: <RcmSectionIcon />,
    children: [{ to: "/rcm/studies", label: "Studies" }],
  },
  {
    to: "/datasets",
    label: "Datasets",
    icon: <DatasetsIcon />,
    children: [{ to: "/datasets/list", label: "All datasets" }],
  },
];

export default function Sidebar({ collapsed, onToggle }) {
  const { user, signOut } = useAuth();
  const { billing } = useAppConfig();
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const [confirmSignOut, setConfirmSignOut] = useState(false);
  const [signingOut, setSigningOut] = useState(false);

  const onSignOut = async () => {
    setSigningOut(true);
    try {
      await signOut();
      navigate("/");
    } finally {
      setSigningOut(false);
      setConfirmSignOut(false);
    }
  };

  return (
    <aside className={"sidebar" + (collapsed ? " collapsed" : "")}>
      <div className="side-head">
        {!collapsed && <div className="side-label-group">Workspace</div>}
        <button
          className="sidebar-toggle"
          onClick={onToggle}
          title={collapsed ? "Expand menu" : "Collapse menu"}
          aria-label={collapsed ? "Expand menu" : "Collapse menu"}
        >
          {collapsed ? "»" : "«"}
        </button>
      </div>
      <nav className="sidebar-nav">
        {ITEMS.map((it) => {
          // Forthcoming sections (no route) render as a disabled "soon" item.
          if (!it.to) {
            return (
              <span
                key={it.label}
                className="side-item disabled"
                title={`${it.label} — coming soon`}
              >
                <span className="side-icon">{it.icon}</span>
                {!collapsed && <span className="side-label">{it.label}</span>}
                {!collapsed && <span className="side-soon">soon</span>}
              </span>
            );
          }
          const sectionActive = pathname.startsWith(it.to);
          return (
            <div key={it.to}>
              <NavLink
                to={it.to}
                end
                className={({ isActive }) => "side-item" + (isActive ? " active" : "")}
                title={it.label}
              >
                <span className="side-icon">{it.icon}</span>
                {!collapsed && <span className="side-label">{it.label}</span>}
              </NavLink>
              {!collapsed && it.children && sectionActive && (
                <div className="side-children">
                  {it.children.map((c) => (
                    <NavLink
                      key={c.to}
                      to={c.to}
                      className={({ isActive }) => "side-subitem" + (isActive ? " active" : "")}
                    >
                      {c.label}
                    </NavLink>
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </nav>

      <div className="side-grow" />

      {!collapsed && <div className="side-label-group">Account</div>}
      {billing && (
        <NavLink
          to="/billing"
          className={({ isActive }) => "side-item" + (isActive ? " active" : "")}
          title="Billing & credits"
        >
          <span className="side-icon"><BillingIcon /></span>
          {!collapsed && <span className="side-label">Billing &amp; credits</span>}
        </NavLink>
      )}
      <a
        className="side-item"
        href="/blog"
        target="_blank"
        rel="noreferrer"
        title="Guides & articles (opens the blog)"
      >
        <span className="side-icon"><GuidesIcon /></span>
        {!collapsed && <span className="side-label">Guides</span>}
      </a>

      <div className="side-foot">
        <span className="ava">{initials(user)}</span>
        {!collapsed && (
          <span className="who" title={user?.email || undefined}>
            <span className="nm" style={{ display: "block" }}>
              {user?.displayName || user?.email || "Account"}
            </span>
            {user?.displayName && user?.email && (
              <span className="rl">{user.email}</span>
            )}
          </span>
        )}
        {!collapsed && (
          <button
            className="side-signout"
            title="Sign out"
            onClick={() => setConfirmSignOut(true)}
          >
            <SignOutIcon />
          </button>
        )}
      </div>

      {confirmSignOut && (
        <Modal
          title="Sign out?"
          className="modal-sm"
          locked={signingOut}
          onClose={() => setConfirmSignOut(false)}
          footer={
            <div style={{ display: "flex", gap: "0.6rem", marginLeft: "auto" }}>
              <button
                className="secondary"
                onClick={() => setConfirmSignOut(false)}
                disabled={signingOut}
              >
                Cancel
              </button>
              <button onClick={onSignOut} disabled={signingOut}>
                {signingOut ? "Signing out…" : "Sign out"}
              </button>
            </div>
          }
        >
          <p className="muted-line" style={{ margin: 0 }}>
            You'll be signed out and returned to the login page. Your saved
            models, RBDs, and datasets stay safe in your account.
          </p>
        </Modal>
      )}
    </aside>
  );
}
