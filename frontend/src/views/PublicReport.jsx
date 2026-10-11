// A report's public page (#30): a header block (title, author or
// organisation, date; the brand bar above carries the logo), the
// introduction, then each section — its note and the item exactly as the
// item's own share page shows it (`Item`, the share page's renderer). Notes
// are plain text: blank lines start paragraphs.

const fmtDate = (iso) => {
  const d = iso ? new Date(iso) : null;
  return d && !Number.isNaN(d.getTime())
    ? d.toLocaleDateString(undefined, { day: "numeric", month: "long", year: "numeric" })
    : null;
};

export function Paragraphs({ text, className }) {
  const parts = String(text || "").split(/\n\s*\n/).map((p) => p.trim()).filter(Boolean);
  if (!parts.length) return null;
  return (
    <div className={className}>
      {parts.map((p, i) => <p key={i}>{p}</p>)}
    </div>
  );
}

export default function ReportView({ report, sharedBy, Item }) {
  const date = fmtDate(report.date);
  const sections = report.sections || [];
  return (
    <article className="report">
      <header className="report-head">
        <h1>{report.name}</h1>
        <div className="report-meta">
          {report.author ? <span>{report.author}</span> : <span>Shared by {sharedBy}</span>}
          {date && <span>{date}</span>}
        </div>
      </header>
      <Paragraphs text={report.introduction} className="report-text report-intro" />
      {sections.map((s, i) => (
        <section className="report-section" key={`${s.collection}-${i}`} aria-labelledby={`report-s${i}`}>
          <div className="report-section-head">
            <div className="report-section-kind">{s.kind}</div>
            <h2 id={`report-s${i}`}>{s.name || "Unavailable item"}</h2>
            <Paragraphs text={s.note} className="report-text" />
          </div>
          {s.artifact ? (
            <Item collection={s.collection} a={s.artifact} />
          ) : (
            <div className="card note"><p>{s.unavailable}</p></div>
          )}
        </section>
      ))}
    </article>
  );
}
