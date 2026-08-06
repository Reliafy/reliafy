# Per-post social cards

Each HTML file here is the source for a 1200x630 og:image under
`public/blog/`. To (re)generate one, screenshot it with Playwright at a
1200x630 viewport and save the PNG to `public/blog/<name>.png`, then set
`image: /blog/<name>.png` in the post's frontmatter. Posts without an
`image` fall back to the site-wide `/og-card.png` — the point of a per-post
card is that LinkedIn previews stop all looking identical.
