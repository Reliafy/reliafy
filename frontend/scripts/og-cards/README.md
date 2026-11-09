# Per-post social cards

Each HTML file here is the source for a 1200x630 og:image under
`public/blog/`. To (re)generate one, screenshot it with Playwright at a
1200x630 viewport and save the PNG to `public/blog/<name>.png`, then set
`image: /blog/<name>.png` in the post's frontmatter (a blog post or a What's
new update alike: it becomes the page's og:image and the enclosure on the
post's item in the LinkedIn feed). Posts without an `image` fall back to the
site-wide `/og-card.png` — the point of a per-post card is that LinkedIn
previews stop all looking identical.

`site-card.html` is the source for that site-wide fallback,
`public/og-card.png`: regenerate it the same way when the site's
positioning changes (keep its words in step with `src/siteCopy.js`).
