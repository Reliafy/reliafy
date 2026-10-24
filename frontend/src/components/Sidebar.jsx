import { useEffect, useRef, useState } from "react";
import { Link, NavLink, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../AuthProvider.jsx";
import { useAppConfig } from "../ConfigProvider.jsx";
import Modal from "./Modal.jsx";
import { publicUrl } from "../firebase.js";
import { useRoles } from "../RolesProvider.jsx";
import { childActive, entryActive, groupBySection } from "../navigation.js";

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
const GraphIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <circle cx="6" cy="6" r="2.5" /><circle cx="18" cy="8" r="2.5" /><circle cx="10" cy="18" r="2.5" />
    <path d="M8.4 6.6l7.2 1M16.6 10.1l-5.1 6M7 8.3l2.2 7.3" />
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

// The menu's icons, by entry id (navigation.js). Instrument hairline strokes.
const icon = (paths) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    {paths}
  </svg>
);
const ICONS = {
  home: icon(<><path d="M4 11.5 12 5l8 6.5" /><path d="M6 10v9h12v-9" /><path d="M10 19v-5h4v5" /></>),
  systems: icon(<><rect x="3" y="4" width="6" height="6" rx="1" /><rect x="15" y="4" width="6" height="6" rx="1" /><rect x="9" y="14" width="6" height="6" rx="1" /><path d="M9 7h6M6 10v4M18 10v4" /></>),
  requirements: icon(<><path d="M9 6h11M9 12h11M9 18h11" /><path d="m3.5 6 1.2 1.2L7 5M3.5 12l1.2 1.2L7 11M3.5 18l1.2 1.2L7 17" /></>),
  assets: icon(<><path d="M12 3 4 7.5v9L12 21l8-4.5v-9z" /><path d="M4 7.5 12 12l8-4.5M12 12v9" /></>),
  maintenance: icon(<path d="M14.7 6.3a4 4 0 0 0-5.4 5.2L3.5 17.3a1.8 1.8 0 0 0 2.5 2.5l5.8-5.8a4 4 0 0 0 5.2-5.4l-2.4 2.4-2.1-.4-.4-2.1z" />),
  risk: icon(<><path d="M12 3 5 6v6c0 4.5 3 7.5 7 9 4-1.5 7-4.5 7-9V6z" /><path d="M8 12.5h2l1.4-3 2.2 6 1.4-3H16" /></>),
  failures: icon(<><path d="M12 4 3 20h18z" /><path d="M12 10v4.5M12 17.5h.01" /></>),
  data: icon(<><ellipse cx="12" cy="6" rx="8" ry="3" /><path d="M4 6v12c0 1.7 3.6 3 8 3s8-1.3 8-3V6" /></>),
  models: icon(<path d="M3 7c3 0 3 10 6 10s3-14 6-14 3 8 6 8" />),
  strategy: icon(<><circle cx="12" cy="12" r="8.5" /><path d="M12 12l4-2.5M12 12v4.5" /><circle cx="12" cy="12" r="1.6" fill="currentColor" stroke="none" /></>),
  forecasts: icon(<><path d="M4 19h16" /><path d="M4 15l4-4 3 3 5-6" /><path d="M16 8h3v3" strokeDasharray="2 2" /></>),
  reports: icon(<><path d="M7 3h7l4 4v14H7z" /><path d="M14 3v4h4M10 12h5M10 16h5" /></>),
  agent: icon(<><rect x="4" y="7" width="16" height="12" rx="2" /><path d="M12 7V4M9 12h.01M15 12h.01M9 16h6" /></>),
};
const MoreIcon = () => icon(<><circle cx="6" cy="12" r="1.2" fill="currentColor" /><circle cx="12" cy="12" r="1.2" fill="currentColor" /><circle cx="18" cy="12" r="1.2" fill="currentColor" /></>);

// One menu entry, with its children while it's the open section. The entry is
// highlighted on its section's pages that no child names (a detail page), and
// always on the collapsed rail, where the children are hidden.
function MenuEntry({ entry, collapsed, pathname }) {
  const active = entryActive(entry, pathname);
  const children = entry.children || [];
  const childOn = children.some((c) => childActive(c, pathname));
  const lit = active && (collapsed || !childOn);
  return (
    <div>
      <Link
        to={entry.to}
        className={"side-item" + (lit ? " active" : "")}
        aria-current={pathname === entry.to ? "page" : undefined}
        title={entry.label}
      >
        <span className="side-icon">{ICONS[entry.id]}</span>
        {!collapsed && <span className="side-label">{entry.label}</span>}
      </Link>
      {!collapsed && active && children.length > 0 && (
        <div className="side-children">
          {children.map((c) => {
            const on = childActive(c, pathname);
            return (
              <Link
                key={c.to}
                to={c.to}
                className={"side-subitem" + (on ? " active" : "")}
                aria-current={pathname === c.to ? "page" : undefined}
              >
                {c.label}
              </Link>
            );
          })}
        </div>
      )}
    </div>
  );
}

// Entries under their section headings (Design, Operate, Analyse; Home and
// Reports/Agent have none). On the collapsed rail a heading is a hairline.
function MenuGroups({ entries, collapsed, pathname, idPrefix }) {
  return groupBySection(entries).map((g) => {
    const headingId = g.section && !collapsed ? `${idPrefix}-${g.section.id}` : undefined;
    return (
      <div
        key={g.key}
        className={"side-group" + (g.key === "end" ? " side-group-end" : "")}
        role={g.section ? "group" : undefined}
        aria-labelledby={headingId}
        aria-label={g.section && collapsed ? g.section.label : undefined}
      >
        {g.section && (
          collapsed
            ? <div className="side-rule" aria-hidden="true" />
            : <div className="side-section" id={headingId}>{g.section.label}</div>
        )}
        {g.entries.map((e) => <MenuEntry key={e.id} entry={e} collapsed={collapsed} pathname={pathname} />)}
      </div>
    );
  });
}

const FOCUSABLE = 'a[href], button:not([disabled]), [tabindex]:not([tabindex="-1"])';

// On a phone (`phone`) the sidebar is an off-canvas drawer: `open` slides it
// in over the page as a modal menu, and `onClose` dismisses it (backdrop tap,
// Escape, the close button). While open, focus moves into the drawer and Tab
// cycles within it.
export default function Sidebar({ collapsed, onToggle, phone = false, open = false, onClose }) {
  const asideRef = useRef(null);
  const { user, signOut } = useAuth();
  const { ai, billing, reliability_agent: agentEnabled } = useAppConfig();
  // Credits only buy AI use; without it the page is plain billing.
  const billingLabel = ai || agentEnabled ? "Billing & credits" : "Billing";
  // The menu (navigation.js): what the user's roles use, then "More".
  const { menu, has } = useRoles();
  const navigate = useNavigate();
  const { pathname } = useLocation();
  // "More" opens by itself when the page shown is one of its entries.
  const moreActive = menu.more.some((e) => entryActive(e, pathname));
  const [moreOpen, setMoreOpen] = useState(moreActive);
  useEffect(() => {
    if (moreActive) setMoreOpen(true);
  }, [moreActive]);
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
      <nav className="sidebar-nav" aria-label="Main">
        <MenuGroups entries={menu.main} collapsed={collapsed} pathname={pathname} idPrefix="side" />
        {menu.more.length > 0 && (
          <>
            <button
              type="button"
              className={"side-item side-more" + (moreActive && !moreOpen ? " active" : "")}
              aria-expanded={moreOpen}
              aria-controls="side-more"
              onClick={() => setMoreOpen((o) => !o)}
              aria-label="More"
              title={moreOpen ? "Hide the rest of the menu" : "More: the rest of the menu"}
            >
              <span className="side-icon"><MoreIcon /></span>
              {!collapsed && <span className="side-label">More</span>}
              {!collapsed && <span className="side-more-caret" aria-hidden="true">{moreOpen ? "▴" : "▾"}</span>}
            </button>
            {moreOpen && (
              <div id="side-more" className="side-more-list">
                <MenuGroups entries={menu.more} collapsed={collapsed} pathname={pathname} idPrefix="side-more" />
              </div>
            )}
          </>
        )}
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
      {/* The Data model page: for graph-access users, and in the menu only where
          the menu preview is on (anyone with access can open /data-model). */}
      {has.graph && has.preview && (
        <NavLink
          to="/data-model"
          className={({ isActive }) => "side-item" + (isActive ? " active" : "")}
          title="Data model — the kinds of thing your maintenance graph holds and how they connect"
        >
          <span className="side-icon"><GraphIcon /></span>
          {!collapsed && <span className="side-label">Data model</span>}
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
