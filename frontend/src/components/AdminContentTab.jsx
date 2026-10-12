import { useEffect, useRef, useState } from "react";
import { getAdminContentCalendar } from "../api.js";
import {
  byDate,
  chipText,
  dayLabel,
  firstLines,
  kindOf,
  LEGEND,
  listDays,
  monthGrid,
  monthLabel,
  monthOf,
  shiftMonth,
  STATUS,
} from "../adminCalendar.js";
import Card, { CardHeader } from "./ui/Card.jsx";
import Chip from "./ui/Chip.jsx";

const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

function ItemChip({ item, selected, onSelect, wide }) {
  const kind = kindOf(item);
  const status = STATUS[item.status] || STATUS.scheduled;
  return (
    <button
      type="button"
      className={`cal-chip k-${kind.key} s-${item.status}` + (selected ? " selected" : "") + (wide ? " wide" : "")}
      onClick={() => onSelect(item)}
      title={`${kind.long} · ${status.label}: ${item.title || ""}`}
      aria-pressed={selected}
    >
      {item.kind === "announcement" && <span aria-hidden="true">↗ </span>}
      {wide ? item.title || kind.label : chipText(item)}
      {wide && <span className="cal-chip-meta"> · {kind.label} · {status.label}</span>}
    </button>
  );
}

function when(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  return d.toLocaleDateString("en-AU", { weekday: "short", day: "numeric", month: "short" });
}

// What's new: its email's state, from the send logs.
function EmailRows({ email }) {
  const test = email.test;
  const list = email.list || {};
  return (
    <dl className="rs-dl cal-dl">
      <div>
        <dt>Email</dt>
        <dd>{email.send === "auto" ? "Automatic (send: auto)" : "Manual (send script)"}</dd>
      </div>
      <div>
        <dt>Auto-send switch</dt>
        <dd>{email.auto_send ? "On" : "Off"}</dd>
      </div>
      <div>
        <dt>Test copy</dt>
        <dd>
          {test?.status === "done"
            ? `Sent ${when(test.at)}`
            : test?.status
              ? `${test.status} ${when(test.at)}`
              : email.send === "auto" && email.test_due
                ? `Due ${dayLabel(email.test_due)}`
                : "—"}
        </dd>
      </div>
      <div>
        <dt>List</dt>
        <dd>
          {list.sent > 0
            ? `${list.sent.toLocaleString()} sent${list.status && list.status !== "done" ? ` (${list.status})` : ""}`
            : list.status
              ? list.status
              : "Not sent"}
        </dd>
      </div>
    </dl>
  );
}

function Detail({ item, isNext }) {
  if (!item) {
    return (
      <Card className="cal-detail">
        <p className="muted-line">Click an item to see it.</p>
      </Card>
    );
  }
  const kind = kindOf(item);
  const status = STATUS[item.status] || STATUS.scheduled;
  const text = firstLines(item.text);
  const external = /^https?:/.test(item.link || "");
  return (
    <Card className="cal-detail">
      <div className="cal-detail-top">
        <span className={`cal-kind k-${kind.key}`}>{kind.long}</span>
        <Chip tone={status.tone}>{status.label}</Chip>
        {isNext && <Chip>Next</Chip>}
      </div>
      <h3 className="cal-detail-title">{item.title || kind.label}</h3>
      <p className="cal-detail-when">
        {dayLabel(item.date, { year: true })}, 10:00 Brisbane
        {item.hold_until && <> · held until {dayLabel(item.hold_until)}, when its page goes live</>}
      </p>
      {item.image && <img className="cal-thumb" src={item.image} alt="" loading="lazy" />}
      {text && <p className="cal-text">{text}</p>}
      {item.status === "planned" || item.status === "missed" ? (
        <p className="muted-line cal-small">
          A calendar slot with no content file yet{item.status === "missed" ? ", and its date has passed" : ""}.
        </p>
      ) : null}
      {item.slot && item.status !== "planned" && item.status !== "missed" && item.slot.date !== item.date && (
        <p className="muted-line cal-small">Fills the {dayLabel(item.slot.date)} slot.</p>
      )}
      {item.link && (
        <p className="cal-small">
          <a href={item.link} target={external ? "_blank" : undefined} rel={external ? "noreferrer" : undefined}>
            {external ? item.link.replace(/^https?:\/\//, "") : item.link}
          </a>
        </p>
      )}
      {item.email && <EmailRows email={item.email} />}
    </Card>
  );
}

function Pipeline({ view }) {
  const p = view.pipeline || {};
  const pr = p.last_pr || {};
  const news = (view.items || []).find((it) => it.kind === "whatsnew" && it.email);
  return (
    <Card className="cal-pipeline">
      <CardHeader title="Pipeline" level={3} />
      <dl className="cal-rows">
        <div>
          <dt>Drafting job</dt>
          <dd>Next run {when(p.next_draft)}, 08:00 Brisbane</dd>
        </div>
        <div>
          <dt>Last content PR</dt>
          <dd>
            {pr.error ? (
              <span className="muted">Unavailable ({pr.error})</span>
            ) : pr.none ? (
              "None yet"
            ) : pr.number ? (
              <>
                <span className="cal-clamp">
                  <a href={pr.url} target="_blank" rel="noreferrer">#{pr.number}</a> {pr.title}
                </span>
                <Chip tone={pr.state === "open" ? "accent" : pr.state === "merged" ? "success" : "neutral"}>
                  {pr.state === "open" ? "Open" : pr.state === "merged" ? "Merged" : "Closed"}
                </Chip>
              </>
            ) : (
              "—"
            )}
          </dd>
        </div>
        <div>
          <dt>Scheduler</dt>
          <dd>
            {p.scheduler ? "Configured" : <span className="warn-text">Not configured</span>}
            <span className="muted"> · auto-send {p.auto_send ? "on" : "off"}</span>
          </dd>
        </div>
        {news && (
          <div>
            <dt>What's new email</dt>
            <dd>
              {dayLabel(news.date)} · {news.email.send === "auto" ? "automatic" : "manual"}
              {news.email.list?.sent > 0 && <> · {news.email.list.sent.toLocaleString()} sent</>}
            </dd>
          </div>
        )}
        <div>
          <dt>LinkedIn feed</dt>
          <dd>
            <a href={p.feed_url} target="_blank" rel="noreferrer" title={p.feed_url}>
              {(p.feed_url || "").replace(/^https?:\/\/[^/]+/, "")}
            </a>
          </dd>
        </div>
      </dl>
    </Card>
  );
}

// The publishing calendar (Content tab): a month grid of what's published,
// scheduled and planned, the next item first, the selected item's detail
// and the pipeline's state beside it. On a phone the grid is a list by day.
export default function AdminContentTab() {
  const thisMonth = monthOf();
  const [month, setMonth] = useState(thisMonth);
  const [state, setState] = useState({ data: null, error: null });
  const [picked, setPicked] = useState(null);
  const detailRef = useRef(null);

  useEffect(() => {
    let alive = true;
    setState((s) => ({ data: s.data, error: null, loading: true }));
    getAdminContentCalendar(month)
      .then((data) => alive && setState({ data, error: null }))
      .catch((e) => alive && setState({ data: null, error: e.message }));
    return () => {
      alive = false;
    };
  }, [month]);

  const view = state.data;
  if (state.error) return <Card className="empty"><p>{state.error}</p></Card>;
  if (!view) return <Card className="empty">Loading…</Card>;

  const items = view.items || [];
  const dated = byDate(items);
  const gaps = new Set(view.gaps || []);
  const selected = (picked && (items.find((it) => it.id === picked.id) || picked)) || view.next;
  const select = (it) => {
    setPicked(it);
    if (window.matchMedia?.("(max-width: 720px)").matches) {
      requestAnimationFrame(() => detailRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }));
    }
  };
  const c = view.counts || {};
  const next = view.next;
  const plural = (n, one, many = one + "s") => `${n} ${n === 1 ? one : many}`;

  return (
    <div className="cal">
      <p className="cal-summary">
        <span>
          {next ? (
            <>
              Next: <b>{next.title || kindOf(next).label}</b> ({kindOf(next).long.toLowerCase()}
              {next.status === "planned" ? ", planned, no file yet" : ""}) on <b>{dayLabel(next.date)}</b>
            </>
          ) : (
            "Nothing scheduled after today"
          )}
        </span>
        <span className="cal-counts">
          {monthLabel(view.month)}: {plural(c.posts || 0, "post")} · {plural(c.linkedin || 0, "LinkedIn item")} ·{" "}
          {plural(c.gaps || 0, "gap")}
          {c.planned ? <> · {c.planned} planned</> : null}
        </span>
      </p>
      {!view.indexed && (
        <p className="muted-line cal-small">
          This build has no content index (it wasn't prerendered), so only the calendar's slots show.
        </p>
      )}

      <div className="cal-layout">
        <Card className="cal-card">
          <div className="cal-head">
            <button type="button" className="ghost sm cal-nav" onClick={() => setMonth(shiftMonth(month, -1))} aria-label="Previous month">‹</button>
            <h2 className="cal-month">{monthLabel(month)}</h2>
            <button type="button" className="ghost sm cal-nav" onClick={() => setMonth(shiftMonth(month, 1))} aria-label="Next month">›</button>
            {month !== thisMonth && (
              <button type="button" className="link sm" onClick={() => setMonth(thisMonth)}>This month</button>
            )}
            {state.loading && <span className="muted cal-small">Loading…</span>}
          </div>

          <div className="cal-grid" role="table" aria-label={`Publishing calendar, ${monthLabel(month)}`}>
            {WEEKDAYS.map((w) => (
              <div key={w} className="cal-wd" role="columnheader">{w}</div>
            ))}
            {monthGrid(month).flat().map((d) => {
              const its = d.inMonth ? dated[d.date] || [] : [];
              const gap = d.inMonth && gaps.has(d.date);
              return (
                <div
                  key={d.date}
                  role="cell"
                  className={
                    "cal-cell" + (d.inMonth ? "" : " out") + (gap ? " gap" : "") + (d.date === view.today ? " today" : "") +
                    (d.weekday >= 5 ? " weekend" : "")
                  }
                >
                  <span className="cal-day">{d.day}</span>
                  {its.map((it) => (
                    <ItemChip key={it.id} item={it} selected={selected?.id === it.id} onSelect={select} />
                  ))}
                  {gap && <span className="cal-gap-note">No LinkedIn</span>}
                </div>
              );
            })}
          </div>

          <ul className="cal-list">
            {listDays(view).map((d) => (
              <li
                key={d.date}
                className={
                  "cal-list-day" + (d.gap ? " gap" : "") + (d.items.length ? "" : " gap-only") + (d.date === view.today ? " today" : "")
                }
              >
                <div className="cal-list-date">{dayLabel(d.date)}</div>
                <div className="cal-list-items">
                  {d.items.map((it) => (
                    <ItemChip key={it.id} item={it} wide selected={selected?.id === it.id} onSelect={select} />
                  ))}
                  {d.gap && <span className="cal-gap-note">No LinkedIn post</span>}
                </div>
              </li>
            ))}
            {listDays(view).length === 0 && <li className="muted-line">Nothing this month.</li>}
          </ul>

          <div className="cal-legend" aria-label="Key">
            {LEGEND.map((l) => (
              <span key={l.key} className={`cal-key k-${l.key}`}>
                {l.key === "announcement" ? "↗ " : ""}
                {l.label}
              </span>
            ))}
            <span className="cal-key-sep" aria-hidden="true" />
            <span className="cal-key s-published">Published</span>
            <span className="cal-key s-scheduled">Scheduled</span>
            <span className="cal-key s-planned">Planned</span>
            <span className="cal-key cal-key-gap">Gap: weekday, no LinkedIn</span>
          </div>
        </Card>

        <div className="cal-side" ref={detailRef}>
          <Detail item={selected} isNext={!!next && selected?.id === next.id} />
          <Pipeline view={view} />
        </div>
      </div>
      <p className="admin-foot">Items go live at 00:00 UTC on their date (10:00 Brisbane), on the site and in the feeds.</p>
    </div>
  );
}
