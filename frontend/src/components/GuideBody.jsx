import { useEffect, useRef } from "react";
import { renderMarkdown } from "../guides.js";

// Renders one guide's header + step body. Shared by the public /guides page and
// the in-app Help drawer. Screenshots that haven't been captured yet (the
// capture harness hasn't run) degrade to a labelled placeholder rather than a
// broken-image icon, so the steps stay readable.
export default function GuideBody({ guide, compact = false }) {
  const ref = useRef(null);

  useEffect(() => {
    const root = ref.current;
    if (!root) return;
    root.querySelectorAll("img").forEach((img) => {
      const mark = () => {
        img.classList.add("guide-img-pending");
        img.setAttribute("data-pending", img.getAttribute("alt") || "Screenshot");
      };
      if (img.complete && img.naturalWidth === 0) mark();
      img.addEventListener("error", mark, { once: true });
    });
  }, [guide]);

  if (!guide) return null;

  return (
    <article className={"guide" + (compact ? " guide-compact" : "")}>
      <header className="guide-head">
        <div className="guide-meta">
          <span>{guide.minutes} min read</span>
          <span className="guide-cat">{guide.category}</span>
        </div>
        <h1>{guide.title}</h1>
        {guide.prerequisites && (
          <p className="guide-prereq"><strong>Before you start:</strong> {guide.prerequisites}</p>
        )}
      </header>

      <div
        ref={ref}
        className="guide-prose"
        dangerouslySetInnerHTML={{ __html: renderMarkdown(guide.body) }}
      />
    </article>
  );
}
