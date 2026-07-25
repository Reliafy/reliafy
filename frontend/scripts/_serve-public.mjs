// Throwaway: serve the cloud (auth-enabled) bundle so the public marketing
// pages — /reference, /guides, /blog — can be browsed locally without
// clobbering dist/, which the local dev server serves in self-host mode.
import { createServer } from "node:http";
import { readFile, stat } from "node:fs/promises";
import { join, extname } from "node:path";
const DIST = new URL("../dist-public/", import.meta.url).pathname;
const MIME = { ".html":"text/html", ".js":"text/javascript", ".css":"text/css",
               ".json":"application/json", ".svg":"image/svg+xml", ".png":"image/png",
               ".webp":"image/webp", ".ico":"image/x-icon", ".woff2":"font/woff2" };
createServer(async (req, res) => {
  const p = req.url.split("?")[0];
  for (const f of [join(DIST, p), join(DIST, "index.html")]) {
    try {
      if (!(await stat(f)).isFile()) continue;
      res.writeHead(200, { "Content-Type": MIME[extname(f)] || "application/octet-stream" });
      return res.end(await readFile(f));
    } catch { /* next */ }
  }
  res.writeHead(404).end("not found");
}).listen(4321, () => console.log("public site on http://localhost:4321"));
