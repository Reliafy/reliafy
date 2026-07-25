import { useEffect, useRef } from "react";
import { renderMarkdown } from "../guides.js";
import { AUTH_DISABLED, publicUrl } from "../firebase.js";

// Marketing sections that only exist in the public build.
const PUBLIC_PREFIXES = ["/guides", "/learn", "/blog"];

// Renders one guide's header + step body. Shared by the public /guides page and
// the in-app Help drawer. Screenshots that haven't been captured yet (the
// capture harness hasn't run) degrade to a labelled placeholder rather than a
// broken-image icon, so the steps stay readable.
export default function GuideBody({ guide, compact = false }) {
  const ref = useRef(null);

  useEffect(() => {
    const root = ref.current;
    if (!root) return;
    // Guides cross-link to /guides, /learn and /blog. Those routes don't exist
    // in an auth-disabled build, where they'd fall through to the app shell and
    // bounce to /modelling — so send them to the public site instead.
    if (AUTH_DISABLED) {
      root.querySelectorAll("a[href^='/']").forEach((a) => {
        const href = a.getAttribute("href") || "";
        if (!PUBLIC_PREFIXES.some((p) => href === p || href.startsWith(`${p}/`))) return;
        a.setAttribute("href", publicUrl(href));
        a.setAttribute("target", "_blank");
        a.setAttribute("rel", "noreferrer");
      });
    }
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
