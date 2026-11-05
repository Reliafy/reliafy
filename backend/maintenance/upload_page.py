"""The phone page a photo link opens: pick or take photos, they upload one at a
time, and if one carries a location the page asks whether to save it as where
the equipment is. Self-contained (no external resources), with a strict CSP set
by the route."""

from __future__ import annotations

import html
import json
import secrets

_STYLE = """
body{font:16px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;margin:0;
background:#f7f7f5;color:#1a1a1a}
main{max-width:34rem;margin:0 auto;padding:1.25rem 1rem 3rem}
h1{font-size:1.25rem;margin:.25rem 0 .25rem}
.muted{color:#666;font-size:.9rem}
.card{background:#fff;border:1px solid #e3e3e0;border-radius:12px;padding:1rem;margin:1rem 0}
label.pick{display:block;text-align:center;background:#2f6df6;color:#fff;border-radius:10px;
padding:.9rem;font-weight:600;cursor:pointer}
input[type=file]{display:none}
ul{list-style:none;padding:0;margin:0}
li{display:flex;gap:.75rem;align-items:center;padding:.5rem 0;border-top:1px solid #eee}
li:first-child{border-top:0}
li img{width:56px;height:56px;object-fit:cover;border-radius:8px;background:#eee}
.ok{color:#15803d}.bad{color:#b42318}
.ask{background:#eef3fe;border:1px solid rgba(47,109,246,.3)}
.ask button{font:inherit;padding:.55rem 1rem;border-radius:8px;border:1px solid #2f6df6;margin-right:.5rem}
.yes{background:#2f6df6;color:#fff}.no{background:#fff;color:#2f6df6}
"""


def render(doc: dict | None, problem: str | None, with_nonce: bool = False):
    nonce = secrets.token_urlsafe(16)
    if doc is None or problem:
        body = f"<main><h1>Reliafy</h1><div class='card'><p>{html.escape(problem or '')}</p></div></main>"
        page = f"<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' " \
               f"content='width=device-width,initial-scale=1'><title>Reliafy photos</title>" \
               f"<style>{_STYLE}</style></head><body>{body}</body></html>"
        return (page, nonce) if with_nonce else page

    name = doc.get("target_name") or "this equipment"
    kind = {"Position": "position", "Location": "location", "Item": "item",
            "WorkOrder": "work order"}.get(doc.get("target_label"), "")
    left = max(0, 20 - len(doc.get("photos") or []))
    # JSON in a script element: escape what could end the element early.
    data = json.dumps({"name": name, "left": left}).replace("<", "\\u003c").replace(">", "\\u003e") \
        .replace("&", "\\u0026")
    body = f"""<main>
<p class="muted">Reliafy Maintenance</p>
<h1>Add photos: {html.escape(name)}</h1>
<p class="muted">{html.escape(kind.capitalize())} · up to {left} more photos with this link.
Nameplates, labels and the whole unit all help.</p>
<label class="pick" for="files">Take or choose photos</label>
<input id="files" type="file" accept="image/*,.heic,.heif" multiple>
<div id="ask" class="card ask" hidden></div>
<div class="card"><ul id="list"><li class="muted" id="empty">No photos yet.</li></ul></div>
<p class="muted">Photos are stored without their location or camera details.</p>
</main>"""
    script = """
const cfg = JSON.parse(document.getElementById('cfg').textContent);
const t = new URLSearchParams(location.search).get('t') || '';
const base = location.pathname;
const list = document.getElementById('list');
let asked = false;
function row(file) {
  document.getElementById('empty')?.remove();
  const li = document.createElement('li');
  const img = document.createElement('img');
  img.src = URL.createObjectURL(file);
  const span = document.createElement('span');
  span.textContent = 'Uploading…';
  li.append(img, span);
  list.prepend(li);
  return span;
}
function askLocation(photoId, offer) {
  asked = true;
  const box = document.getElementById('ask');
  box.hidden = false;
  box.textContent = '';
  const p = document.createElement('p');
  p.textContent = `This photo has a location (${offer.lat.toFixed(5)}, ${offer.lon.toFixed(5)}). ` +
    `Save it as where ${cfg.name} is?`;
  const yes = document.createElement('button'); yes.className = 'yes'; yes.textContent = 'Save location';
  const no = document.createElement('button'); no.className = 'no'; no.textContent = 'No thanks';
  const answer = async (save) => {
    yes.disabled = no.disabled = true;
    const r = await fetch(`${base}/location?t=${encodeURIComponent(t)}`, {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({photo_id: photoId, save})});
    box.textContent = r.ok ? (save ? 'Location saved.' : 'Location not saved.') : 'Could not save the answer.';
  };
  yes.onclick = () => answer(true);
  no.onclick = () => answer(false);
  box.append(p, yes, no);
}
document.getElementById('files').addEventListener('change', async (e) => {
  for (const file of e.target.files) {
    const status = row(file);
    try {
      const r = await fetch(`${base}?t=${encodeURIComponent(t)}`, {
        method: 'POST', headers: {'Content-Type': file.type || 'application/octet-stream'}, body: file});
      const d = await r.json().catch(() => ({}));
      if (!r.ok) { status.textContent = d.detail || 'Upload failed.'; status.className = 'bad'; continue; }
      status.textContent = 'Added'; status.className = 'ok';
      if (d.location_offer && !asked) askLocation(d.photo_id, d.location_offer);
    } catch (err) {
      status.textContent = 'Upload failed: check the connection.'; status.className = 'bad';
    }
  }
  e.target.value = '';
});
"""
    page = (f"<!doctype html><html><head><meta charset='utf-8'>"
            f"<meta name='viewport' content='width=device-width,initial-scale=1'>"
            f"<meta name='robots' content='noindex'><title>Add photos · Reliafy</title>"
            f"<style>{_STYLE}</style></head><body>{body}"
            f"<script id='cfg' type='application/json' nonce='{nonce}'>{data}</script>"
            f"<script nonce='{nonce}'>{script}</script></body></html>")
    return (page, nonce) if with_nonce else page
