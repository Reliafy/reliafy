import { useEffect, useRef, useState } from "react";
import { Link, NavLink, useLocation, useNavigate } from "react-router-dom";
import { NAV, activeNav } from "../sections.js";
import { useAuth } from "../AuthProvider.jsx";
import { useAppConfig } from "../ConfigProvider.jsx";
import Modal from "./Modal.jsx";
import { publicUrl } from "../firebase.js";
import { getMaintenanceAccess } from "../api.js";

const SignOutIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M16 17l5-5-5-5M21 12H9M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
  </svg>
);

// Two-letter avatar from a display name or email.
export function initials(user) {
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

const MaintenanceIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M14.7 6.3a4 4 0 0 0-5.4 5.2L3.5 17.3a1.8 1.8 0 0 0 2.5 2.5l5.8-5.8a4 4 0 0 0 5.2-5.4l-2.4 2.4-2.1-.4-.4-2.1z" />
  </svg>
);

const AgentIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <rect x="4" y="7" width="16" height="12" rx="2" />
    <path d="M12 7V4M9 12h.01M15 12h.01M9 16h6" />
  </svg>
);

const ApiIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M8 9l-4 3 4 3M16 9l4 3-4 3M13 6l-2 12" />
  </svg>
);
const NewsIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9z" />
    <path d="M19 16v4M17 18h4" />
  </svg>
);
const SettingsIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <circle cx="12" cy="12" r="3" />
    <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
  </svg>
);
const BillingIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <rect x="3" y="5" width="18" height="14" rx="2" />
    <path d="M3 10h18" />
  </svg>
);

const HomeIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M3.5 11 12 4l8.5 7" />
    <path d="M5.5 9.5V20h13V9.5" />
    <path d="M10 20v-5.5h4V20" />
  </svg>
);

// The menu itself is data (sections.js, with its tests); here each section
// gets its icon. A section's children show under it while it's the current
// section; the current page is highlighted, the child when there is one.
const ICONS = {
  home: <HomeIcon />,
  modelling: <ModellingIcon />,
  rbds: <RbdIcon />,
  strategy: <StrategyIcon />,
  fleet: <FleetIcon />,
  rcm: <RcmSectionIcon />,
  maintenance: <MaintenanceIcon />,
  agent: <AgentIcon />,
};

const FOCUSABLE = 'a[href], button:not([disabled]), [tabindex]:not([tabindex="-1"])';

// On a phone (`phone`) the sidebar is an off-canvas drawer: `open` slides it
// in over the page as a modal menu, and `onClose` dismisses it (backdrop tap,
// Escape, the close button). While open, focus moves into the drawer and Tab
// cycles within it.
export default function Sidebar({ collapsed, onToggle, phone = false, open = false, onClose }) {
  const asideRef = useRef(null);
  const { user, signOut } = useAuth();
  const { ai, billing, reliability_agent: agentEnabled, maintenance: maintenanceEnabled } = useAppConfig();
  // Credits only buy AI use; without it the page is plain billing.
  const billingLabel = ai || agentEnabled ? "Billing & credits" : "Billing";
  // The Reliability Agent surface is behind a feature flag (hidden until ready).
  const [maintenanceAllowed, setMaintenanceAllowed] = useState(false);
  useEffect(() => {
    if (!maintenanceEnabled) return;
    getMaintenanceAccess().then((a) => setMaintenanceAllowed(!!a.allowed));
  }, [maintenanceEnabled]);
  const items = NAV.filter((it) => (it.gate !== "agent" || agentEnabled)
    && (it.gate !== "maintenance" || (maintenanceEnabled && maintenanceAllowed)));
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const current = activeNav(pathname);
  const [confirmSignOut, setConfirmSignOut] = useState(false);
  const [signingOut, setSigningOut] = useState(false);

  const drawerOpen = phone && open;
  useEffect(() => {
    if (!drawerOpen) return undefined;
    const aside = asideRef.current;
    const focusables = () => [...aside.querySelectorAll(FOCUSABLE)];
    focusables()[0]?.focus();
    const onKey = (e) => {
      // A dialog opened from the drawer (sign out) handles its own keys.
      if (document.querySelector(".overlay")) return;
      if (e.key === "Escape") {
        e.preventDefault();
        onClose?.();
      } else if (e.key === "Tab") {
        const els = focusables();
        if (!els.length) return;
        const first = els[0];
        const last = els[els.length - 1];
        if (e.shiftKey && (document.activeElement === first || !aside.contains(document.activeElement))) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && (document.activeElement === last || !aside.contains(document.activeElement))) {
          e.preventDefault();
          first.focus();
        }
      }
    };
    document.addEventListener("keydown", onKey);
    // The page behind the drawer shouldn't scroll under a finger.
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = prevOverflow;
    };
  }, [drawerOpen, onClose]);
  // Any link closes the drawer, including one to the page already shown
  // (which doesn't change the route).
  const onDrawerClick = (e) => {
    if (e.target.closest("a[href]")) onClose?.();
  };

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
    <>
    {drawerOpen && <div className="sidebar-backdrop" onClick={onClose} aria-hidden="true" />}
    <aside
      ref={asideRef}
      id="app-sidebar"
      className={"sidebar" + (collapsed ? " collapsed" : "") + (phone ? " drawer" : "") + (drawerOpen ? " open" : "")}
      {...(drawerOpen ? { role: "dialog", "aria-modal": "true", "aria-label": "Menu" } : {})}
      onClick={drawerOpen ? onDrawerClick : undefined}
    >
      <div className="side-head">
        {!collapsed && <div className="side-label-group">Workspace</div>}
        {phone ? (
          <button
            type="button"
            className="sidebar-toggle"
            onClick={onClose}
            title="Close menu"
            aria-label="Close menu"
          >
            ×
          </button>
        ) : (
          <button
            className="sidebar-toggle"
            onClick={onToggle}
            title={collapsed ? "Expand menu" : "Collapse menu"}
            aria-label={collapsed ? "Expand menu" : "Collapse menu"}
          >
            {collapsed ? "»" : "«"}
          </button>
        )}
      </div>
      <nav className="sidebar-nav">
        {items.map((it) => {
          const sectionActive = current.section === it.key;
          return (
            <div key={it.to}>
              <Link
                to={it.to}
                className={"side-item" + (sectionActive && (collapsed || !current.child) ? " active" : "")}
                aria-current={sectionActive && !current.child && pathname === it.to ? "page" : undefined}
                title={it.label}
              >
                <span className="side-icon">{ICONS[it.key]}</span>
                {!collapsed && <span className="side-label">{it.label}</span>}
              </Link>
              {!collapsed && it.children && sectionActive && (
                <div className="side-children">
                  {it.children.map((c) => (
                    <Link
                      key={c.to}
                      to={c.to}
                      className={"side-subitem" + (current.child === c.to ? " active" : "")}
                      aria-current={pathname === c.to ? "page" : undefined}
                    >
                      {c.label}
                    </Link>
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </nav>

      <div className="side-grow" />

      {!collapsed && <div className="side-label-group">Account</div>}
      <NavLink
        to="/settings"
        className={({ isActive }) => "side-item" + (isActive ? " active" : "")}
        title="Settings — profile, sample data, API access"
      >
        <span className="side-icon"><SettingsIcon /></span>
        {!collapsed && <span className="side-label">Settings</span>}
      </NavLink>
      {billing && (
        <NavLink
          to="/billing"
          className={({ isActive }) => "side-item" + (isActive ? " active" : "")}
          title={billingLabel}
        >
          <span className="side-icon"><BillingIcon /></span>
          {!collapsed && <span className="side-label">{billingLabel}</span>}
        </NavLink>
      )}
      <a
        className="side-item"
        href="/api-docs"
        target="_blank"
        rel="noreferrer"
        title="API docs — the reliability API reference (opens in a new tab)"
      >
        <span className="side-icon"><ApiIcon /></span>
        {!collapsed && <span className="side-label">API docs</span>}
      </a>
      <a
        className="side-item"
        href={publicUrl("/whats-new")}
        target="_blank"
        rel="noreferrer"
        title="What's new — recent product updates (opens in a new tab)"
      >
        <span className="side-icon"><NewsIcon /></span>
        {!collapsed && <span className="side-label">What's new</span>}
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
    </>
  );
}
