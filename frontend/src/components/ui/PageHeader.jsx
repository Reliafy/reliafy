import { Link } from "react-router-dom";
import OverflowMenu from "../OverflowMenu.jsx";
import CopyIdItem from "../CopyId.jsx";

// A page's header (#310): breadcrumb, the item's own name, one muted meta
// line, and actions on the right — one primary (the next step), the rest
// secondary, and a ⋯ menu that also holds "Copy ID".
//
//   crumbs    [{ label, to }] — the parents only; the title names the page
//   title     node — the item's name
//   badges    node — chips after the title (Sample, Shared, Unsaved)
//   meta      node — one muted line (kind, unit, when saved)
//   primary   node — the one primary button, if this view has a next step
//   actions   node — secondary buttons, shown before the primary
//   menu      node — .ovm-item buttons for the ⋯ menu (share, delete last)
//   id        string — adds "Copy ID" to the ⋯ menu
//   children  extra content under the meta line (a notice, a description)
export default function PageHeader({ crumbs = [], title, badges, meta, primary, actions, menu, id, children, className }) {
  const hasMenu = !!menu || !!id;
  return (
    <header className={"page-header" + (className ? " " + className : "")}>
      <div className="ph-main">
        {crumbs.length > 0 && (
          <nav className="crumb" aria-label="Breadcrumb">
            {crumbs.map((c, i) => (
              <span key={i}>
                {i > 0 && <span className="crumb-sep" aria-hidden="true"> / </span>}
                {c.to ? (
                  <Link className="crumb-link" to={c.to}>{c.label}</Link>
                ) : c.onClick ? (
                  <button type="button" className="crumb-link" onClick={c.onClick}>{c.label}</button>
                ) : (
                  <span>{c.label}</span>
                )}
              </span>
            ))}
          </nav>
        )}
        <div className="title-row">
          <h1>{title}</h1>
          {badges}
        </div>
        {meta && <div className="ph-meta">{meta}</div>}
        {children}
      </div>
      {(primary || actions || hasMenu) && (
        <div className="head-actions">
          {actions}
          {primary}
          {hasMenu && (
            <OverflowMenu>
              {/* First, so a destructive item in menu stays last. */}
              {id && <CopyIdItem id={id} />}
              {menu}
            </OverflowMenu>
          )}
        </div>
      )}
    </header>
  );
}
