import test from "node:test";
import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { parseFrontmatter, slugFromPath } from "./frontmatter.js";
import { announcementText, linkedinFeed, siteUrl, socialPost } from "./contentFeed.js";

const CONTENT = join(dirname(fileURLToPath(import.meta.url)), "content");

test("parseFrontmatter: plain keys, quotes, and a block scalar", () => {
  const raw = [
    "---",
    'title: "A: title"',
    "date: 2026-11-02",
    "linkedin: |",
    "  First line: with a colon.",
    "",
    "  Second paragraph.",
    "    indented more",
    "send: auto",
    "---",
    "Body text",
  ].join("\n");
  const { meta, body } = parseFrontmatter(raw);
  assert.equal(meta.title, "A: title");
  assert.equal(meta.date, "2026-11-02");
  assert.equal(meta.linkedin, "First line: with a colon.\n\nSecond paragraph.\n  indented more");
  assert.equal(meta.send, "auto");
  // Indented lines belong to the block, never become keys.
  assert.equal(meta["First line"], undefined);
  assert.equal(body, "Body text");
});

test("slugFromPath drops the date prefix", () => {
  assert.equal(slugFromPath("content/social/2026-10-14-mttf-tip.md"), "mttf-tip");
});

test("siteUrl accepts site paths and Reliafy URLs only", () => {
  assert.equal(siteUrl("/blog/x", "t"), "https://reliafy.com/blog/x");
  assert.equal(siteUrl("https://reliafy.com/learn/b10-life", "t"), "https://reliafy.com/learn/b10-life");
  assert.throws(() => siteUrl("https://example.org/x", "t"), /not a Reliafy URL/);
  assert.throws(() => siteUrl("//evil.example/x", "t"), /not a Reliafy URL/);
  assert.throws(() => siteUrl("http://reliafy.com/x", "t"), /not a Reliafy URL/);
});

const SHORT = "---\ndate: 2026-10-14\nlink: /blog/import-rbds\nimage: /blog/card.png\n---\nLine one of the post.\n\nMore text.\n";

test("socialPost parses a short post and validates it", () => {
  const p = socialPost("content/social/2026-10-14-import-tip.md", SHORT);
  assert.deepEqual(p, {
    id: "2026-10-14-import-tip",
    slug: "import-tip",
    date: "2026-10-14",
    link: "https://reliafy.com/blog/import-rbds",
    image: "https://reliafy.com/blog/card.png",
    text: "Line one of the post.\n\nMore text.",
  });
  assert.throws(() => socialPost("content/social/import-tip.md", SHORT), /YYYY-MM-DD/);
  assert.throws(() => socialPost("content/social/2026-10-15-import-tip.md", SHORT), /differs/);
  assert.throws(() => socialPost("content/social/2026-10-14-x.md", "---\ndate: 2026-10-14\n---\n  \n"), /empty/);
  assert.throws(
    () => socialPost("content/social/2026-10-14-x.md", "---\ndate: 2026-10-14\nlink: https://example.org\n---\nHi"),
    /not a Reliafy URL/,
  );
});

const POSTS = [
  { slug: "import-rbds", title: "Import your RBDs", summary: "BlockSim and more.", date: "2026-10-19", image: "/blog/card.png", linkedin: "" },
  { slug: "spreadsheets", title: "Spreadsheets", summary: "Where it goes wrong.", date: "2026-10-26", linkedin: "Exact LinkedIn text.\n\nTwo paragraphs." },
  { slug: "old-post", title: "Old", summary: "Already announced.", date: "2026-09-22", linkedin: "" },
];
const UPDATES = [
  { slug: "november-2026", title: "What's new: November", summary: "Lots.", date: "2026-11-02", linkedin: "" },
  { slug: "october-2026", title: "What's new: October", summary: "Old.", date: "2026-10-01", linkedin: "" },
];

test("announcementText: the linkedin field, else title and summary", () => {
  assert.equal(announcementText(POSTS[1]), "Exact LinkedIn text.\n\nTwo paragraphs.");
  assert.equal(announcementText(POSTS[0]), "Import your RBDs\n\nBlockSim and more.");
});

test("linkedinFeed merges short posts and announcements with unique guids", () => {
  const social = [
    socialPost("content/social/2026-10-14-import-tip.md", SHORT),
    socialPost("content/social/2026-10-20-sheet-tip.md", "---\ndate: 2026-10-20\nlink: https://reliafy.com/blog/spreadsheets?x=1\n---\nA tip."),
    socialPost("content/social/2026-10-21-no-link.md", "---\ndate: 2026-10-21\n---\nJust words."),
  ];
  const feed = linkedinFeed({ posts: POSTS, updates: UPDATES, social });
  assert.equal(feed.path, "/social/feed.xml");
  assert.deepEqual(feed.utm, { source: "linkedin", medium: "social" });
  const byGuid = Object.fromEntries(feed.items.map((i) => [i.guid, i]));
  // Announcements before LINKEDIN_START were posted through the old Zap.
  assert.equal(byGuid["https://reliafy.com/blog/old-post#linkedin"], undefined);
  assert.equal(byGuid["https://reliafy.com/whats-new/october-2026#linkedin"], undefined);
  assert.deepEqual(Object.keys(byGuid).sort(), [
    "https://reliafy.com/blog/import-rbds#linkedin",
    "https://reliafy.com/blog/spreadsheets#linkedin",
    "https://reliafy.com/social/2026-10-14-import-tip",
    "https://reliafy.com/social/2026-10-20-sheet-tip",
    "https://reliafy.com/social/2026-10-21-no-link",
    "https://reliafy.com/whats-new/november-2026#linkedin",
  ]);
  assert.ok(feed.items.every((i) => i.permalink === false));

  const blog = byGuid["https://reliafy.com/blog/spreadsheets#linkedin"];
  assert.equal(blog.summary, "Exact LinkedIn text.\n\nTwo paragraphs.");
  assert.equal(blog.link, "https://reliafy.com/blog/spreadsheets");
  assert.equal(blog.campaign, "spreadsheets");
  assert.equal(blog.date, "2026-10-26");
  const fallback = byGuid["https://reliafy.com/blog/import-rbds#linkedin"];
  assert.equal(fallback.summary, "Import your RBDs\n\nBlockSim and more.");
  assert.equal(fallback.image, "https://reliafy.com/blog/card.png");
  const update = byGuid["https://reliafy.com/whats-new/november-2026#linkedin"];
  assert.equal(update.link, "https://reliafy.com/whats-new/november-2026");

  // A short post linking to a post that isn't out yet is held until it is.
  const early = byGuid["https://reliafy.com/social/2026-10-14-import-tip"];
  assert.equal(early.hold_until, "2026-10-19");
  assert.equal(early.campaign, "import-tip");
  assert.equal(early.summary, "Line one of the post.\n\nMore text.");
  assert.equal(early.title, "Line one of the post.");
  assert.equal(byGuid["https://reliafy.com/social/2026-10-20-sheet-tip"].hold_until, "2026-10-26");
  assert.equal(byGuid["https://reliafy.com/social/2026-10-21-no-link"].hold_until, "");
  // Newest first.
  const dates = feed.items.map((i) => i.date);
  assert.deepEqual(dates, [...dates].sort().reverse());
});

test("linkedinFeed refuses duplicate guids", () => {
  const p = socialPost("content/social/2026-10-14-import-tip.md", SHORT);
  assert.throws(() => linkedinFeed({ social: [p, p] }), /share the guid/);
});

// The real content: every short post must parse, and every blog post and
// update must give a non-empty announcement.
test("every committed short post, blog post and update is feed-ready", () => {
  const dir = (name) => {
    try {
      return readdirSync(join(CONTENT, name)).filter((f) => f.endsWith(".md"));
    } catch {
      return [];
    }
  };
  const social = dir("social").map((f) => socialPost(`content/social/${f}`, readFileSync(join(CONTENT, "social", f), "utf8")));
  const load = (name) =>
    dir(name).map((f) => {
      const { meta } = parseFrontmatter(readFileSync(join(CONTENT, name, f), "utf8"));
      return { slug: meta.slug || slugFromPath(f), title: meta.title || "", summary: meta.summary || "", date: meta.date || "", image: meta.image || "", linkedin: meta.linkedin || "" };
    });
  const posts = load("blog");
  const updates = load("updates");
  const feed = linkedinFeed({ posts, updates, social });
  for (const item of feed.items) assert.ok(item.summary.trim(), `${item.guid} has no text`);
  for (const u of updates) {
    const { meta } = parseFrontmatter(readFileSync(join(CONTENT, "updates", dir("updates").find((f) => slugFromPath(f) === u.slug)), "utf8"));
    assert.ok(!meta.send || meta.send === "auto", `${u.slug}: send must be "auto" or absent`);
  }
});
