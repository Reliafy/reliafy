import { useState } from "react";
import { Link } from "react-router-dom";
import ListSearch, { matches } from "./ListSearch.jsx";
import PageHeader from "./ui/PageHeader.jsx";
import Select from "./Select.jsx";
import { ShowMeHow } from "./Walkthrough.jsx";
import { openGuide } from "./HelpButton.jsx";
import { getWalkthrough } from "../walkthroughs.js";
import { SampleGroups } from "./LibRows.jsx";
import { useNavCrumbs } from "../RolesProvider.jsx";

// One template for every section's landing page and its children's pages:
//
//   header   title, a one-line purpose and "Show me how", the main action
//            ("New …") top right with any secondary actions beside it;
//   starter  at most one starter banner, styled the same everywhere;
//   list     the section's full list: search, a type filter where the section
//            has types, the user's own items then the shared samples, and
//            one empty state that points at the samples and the guide.
//
// A section's own landing page has no label above its title; a child page
// (Models › Non-repairable models) shows its menu entry there, linked.

// "Show me how": the section's walkthrough when it has one (it opens a sample
// and points at each step), else its how-to guide in the Help drawer.
export function ShowMe({ help, children = "Show me how" }) {
  if (!help) return null;
  if (help.walkthrough && getWalkthrough(help.walkthrough)) {
    return <ShowMeHow id={help.walkthrough}>{children}</ShowMeHow>;
  }
  if (!help.guide) return null;
  return (
    <button type="button" className="link wt-launch" onClick={() => openGuide(help.guide)}>
      {children}
    </button>
  );
}

//   section  the menu entry's id (navigation.js): on a child page its label
//            shows above the title, linked (none on the entry's landing page)
//   title, purpose, help ({ walkthrough?, guide? }), primary, actions, menu
export function SectionHeader({ section, title, purpose, help, primary, actions, menu, children }) {
  const crumbs = useNavCrumbs(section);
  return (
    <PageHeader
      className="section-header"
      crumbs={section ? crumbs : []}
      title={title}
      meta={(purpose || help) && (
        <span className="sh-purpose">
          {purpose && <span className="sh-purpose-text" title={typeof purpose === "string" ? purpose : undefined}>{purpose}</span>}
          <ShowMe help={help} />
        </span>
      )}
      primary={primary}
      actions={actions}
      menu={menu}
    >
      {children}
    </PageHeader>
  );
}

// The one starter banner a section may show: an icon, a title, a line, and a
// link (or a button) to start.
export function SectionStarter({ icon, title, body, to, state, onClick, cta = "Start" }) {
  return (
    <div className="sif-card section-starter">
      {icon && <span className="sif-card-ic">{icon}</span>}
      <div className="sif-card-body">
        <b>{title}</b>
        <span>{body}</span>
      </div>
      {to ? (
        <Link className="sif-card-cta" to={to} state={state} onClick={onClick}>{cta} →</Link>
      ) : (
        <button type="button" className="link sif-card-cta" onClick={onClick}>{cta} →</button>
      )}
    </div>
  );
}

// The empty list: what goes here, the section's main action, and the two ways
// in for someone who hasn't made one yet: the samples (hidden ones come back
// from Settings) and the guide.
export function SectionEmpty({ title, body, action, help }) {
  return (
    <div className="card empty section-empty">
      <h2>{title}</h2>
      {body && <p>{body}</p>}
      {action && <div className="section-empty-action">{action}</div>}
      <p className="section-empty-more">
        Samples hidden? <Link to="/settings">Restore the sample data in Settings</Link>
        {help && <> · <ShowMe help={help} /></>}
      </p>
    </div>
  );
}

// The section's list.
//
//   rows      the items, or null while loading
//   noun      [one, many] for the count ("model", "models")
//   fields    (row) => the strings a search matches on (the id always counts)
//   types     optional [{ value, label }]: a type filter, with typeOf(row)
//   head      the <th> cells; render(row) returns its <tr>
//   empty     { title, body, action } for SectionEmpty, with help
//   className extra class on the table's wrapper (e.g. "ds-lib")
//   tagsOf    optional (row) => its tags: chips that filter the list (a row must
//             have every chip that's on)
export function SectionList({
  rows, noun, fields, types, typeOf, tagsOf, head, render, empty, help, placeholder, className = "",
}) {
  const [query, setQuery] = useState("");
  const [type, setType] = useState("");
  const [on, setOn] = useState([]);
  if (rows === null || rows === undefined) return <div className="card empty">Loading…</div>;
  if (!rows.length) return <SectionEmpty {...empty} help={help} />;
  const [one, many] = noun;
  const visible = rows.filter((r) =>
    (!type || typeOf(r) === type)
    && (!on.length || on.every((t) => (tagsOf(r) || []).includes(t)))
    && matches(query, ...(fields ? fields(r) : [r.name]), r.id));
  const allTags = tagsOf ? [...new Set(rows.flatMap((r) => tagsOf(r) || []))] : [];
  const toggle = (t) => setOn((cur) => (cur.includes(t) ? cur.filter((x) => x !== t) : [...cur, t]));
  const present = types ? types.filter((t) => rows.some((r) => typeOf(r) === t.value)) : [];
  return (
    <>
      <div className="tablebar section-tablebar">
        <span className="count">
          {visible.length === rows.length
            ? `${rows.length} ${rows.length === 1 ? one : many}`
            : `${visible.length} of ${rows.length} ${many}`}
        </span>
        {allTags.length > 0 && (
          <div className="section-tags" role="group" aria-label="Filter by what it holds">
            {allTags.map((t) => (
              <button key={t} type="button" aria-pressed={on.includes(t)}
                className={"chip chip-btn " + (on.includes(t) ? "chip-accent" : "chip-neutral")}
                onClick={() => toggle(t)}>
                {t}
              </button>
            ))}
            {on.length > 0 && <button type="button" className="linkish" onClick={() => setOn([])}>Clear</button>}
          </div>
        )}
        <span className="grow" />
        {present.length > 1 && (
          <Select
            className="section-type-filter"
            ariaLabel="Type"
            value={type}
            onChange={setType}
            options={[{ value: "", label: "All types" }, ...present]}
          />
        )}
        <ListSearch value={query} onChange={setQuery} placeholder={placeholder || `Search ${many}…`} />
      </div>
      <div className={"lib" + (className ? " " + className : "")}>
        <table className="lib-table">
          <thead><tr>{head}</tr></thead>
          <tbody>
            <SampleGroups rows={visible} cols={Array.isArray(head) ? head.length : 5} render={render} />
          </tbody>
        </table>
        {!visible.length && <p className="section-nomatch">Nothing matches.</p>}
      </div>
    </>
  );
}
