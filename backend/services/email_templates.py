"""Branded HTML email layout (the site's "Instrument" design, email-safe).

Email clients ignore stylesheets, strip SVG and <style> blocks unevenly, and
Outlook renders with Word — so this is the boring, robust recipe: nested
tables, every style inline, a hosted PNG logo, a bulletproof button, and web
fonts only as a progressive enhancement (Apple Mail / iOS pick up IBM Plex
Sans; Gmail falls back to the system stack).

Palette mirrors frontend/src/index.css :root.
"""

from __future__ import annotations

import html as html_lib
import re

# Instrument tokens (frontend/src/index.css).
INK = "#14171c"
MUTED = "#6c727c"
FAINT = "#9aa0a8"
ACCENT = "#2f6df6"
ACCENT_TINT = "#eaf0fe"
PANEL = "#ffffff"
GROUND = "#f6f5f1"
LINE = "#e8e7e2"

FONT = "'IBM Plex Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif"
MONO = "'IBM Plex Mono', ui-monospace, SFMono-Regular, Menlo, Consolas, monospace"

LOGO_PATH = "/email/logo-96.png"  # frontend/public/email/logo-96.png, shown at 32px

_esc = html_lib.escape

# Inline styles for the tags markdown produces. Applied to tags that don't
# already carry a style attribute.
_BODY_STYLES = {
    "h1": f"margin:28px 0 8px;font-size:22px;line-height:1.3;font-weight:600;letter-spacing:-0.02em;color:{INK};",
    "h2": f"margin:30px 0 8px;font-size:17px;line-height:1.35;font-weight:600;letter-spacing:-0.01em;color:{INK};",
    "h3": f"margin:24px 0 6px;font-size:15px;line-height:1.4;font-weight:600;color:{INK};",
    "p": f"margin:0 0 14px;font-size:15px;line-height:1.65;color:{INK};",
    "ul": "margin:0 0 14px;padding:0 0 0 20px;",
    "ol": "margin:0 0 14px;padding:0 0 0 20px;",
    "li": f"margin:0 0 6px;font-size:15px;line-height:1.6;color:{INK};",
    "a": f"color:{ACCENT};text-decoration:underline;",
    "strong": f"font-weight:600;color:{INK};",
    "code": f"font-family:{MONO};font-size:13px;background:{GROUND};border:1px solid {LINE};border-radius:4px;padding:1px 5px;",
    "blockquote": f"margin:0 0 14px;padding:4px 0 4px 14px;border-left:3px solid {LINE};color:{MUTED};",
    "hr": f"border:none;border-top:1px solid {LINE};margin:24px 0;",
}


def style_body(fragment: str) -> str:
    """Inline the design's styles onto a rendered-markdown HTML fragment."""
    def repl(m: re.Match) -> str:
        tag, attrs = m.group(1), m.group(2) or ""
        style = _BODY_STYLES.get(tag.lower())
        if not style or "style=" in attrs:
            return m.group(0)
        return f"<{tag}{attrs} style=\"{style}\">"
    return re.sub(r"<(h1|h2|h3|p|ul|ol|li|a|strong|code|blockquote|hr)(\s[^>]*)?>", repl, fragment)


def button(label: str, href: str) -> str:
    """Bulletproof button (renders as a button in Outlook too)."""
    return (
        f'<table role="presentation" cellpadding="0" cellspacing="0" border="0" style="margin:8px 0 4px;">'
        f'<tr><td bgcolor="{ACCENT}" style="border-radius:8px;">'
        f'<a href="{_esc(href)}" style="display:inline-block;padding:11px 20px;font-family:{FONT};'
        f'font-size:15px;font-weight:600;line-height:1;color:#ffffff;text-decoration:none;border-radius:8px;">'
        f'{_esc(label)}</a></td></tr></table>'
    )


def layout(
    *,
    body_html: str,
    base_url: str,
    title: str = "",
    eyebrow: str = "",
    lead: str = "",
    preheader: str = "",
    cta: tuple[str, str] | None = None,
    footer_html: str = "",
    logo_src: str | None = None,
) -> str:
    """Wrap ``body_html`` (already styled) in the branded shell.

    ``logo_src`` overrides the hosted logo (e.g. ``cid:logo`` for a test sent
    before the logo is deployed).
    """
    base = base_url.rstrip("/")
    logo = logo_src or f"{base}{LOGO_PATH}"
    pre = (
        f'<div style="display:none;max-height:0;overflow:hidden;mso-hide:all;font-size:1px;'
        f'line-height:1px;color:{GROUND};opacity:0;">{_esc(preheader)}'
        + "&#8204;&nbsp;" * 40 + "</div>"
    ) if preheader else ""
    eyebrow_html = (
        f'<div style="margin:0 0 10px;font-family:{MONO};font-size:11px;font-weight:500;'
        f'letter-spacing:0.08em;text-transform:uppercase;color:{ACCENT};">{_esc(eyebrow)}</div>'
    ) if eyebrow else ""
    title_html = (
        f'<h1 style="margin:0 0 10px;font-family:{FONT};font-size:24px;line-height:1.25;'
        f'font-weight:600;letter-spacing:-0.02em;color:{INK};">{_esc(title)}</h1>'
    ) if title else ""
    lead_html = (
        f'<p style="margin:0 0 22px;font-family:{FONT};font-size:16px;line-height:1.55;color:{MUTED};">'
        f'{_esc(lead)}</p>'
    ) if lead else ""
    rule = (
        f'<div style="height:1px;line-height:1px;font-size:1px;background:{LINE};margin:0 0 24px;">&nbsp;</div>'
    ) if (title or lead) else ""
    cta_html = f'<div style="margin:28px 0 4px;">{button(*cta)}</div>' if cta else ""

    return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light"><meta name="supported-color-schemes" content="light">
<title>{_esc(title or "Reliafy")}</title>
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@500&family=IBM+Plex+Sans:wght@400;600&display=swap" rel="stylesheet">
</head>
<body style="margin:0;padding:0;background:{GROUND};-webkit-text-size-adjust:100%;">
{pre}
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" bgcolor="{GROUND}" style="background:{GROUND};">
<tr><td align="center" style="padding:28px 16px 36px;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="max-width:600px;">
    <tr><td style="padding:0 4px 18px;">
      <a href="{_esc(base)}/" style="text-decoration:none;">
        <table role="presentation" cellpadding="0" cellspacing="0" border="0"><tr>
          <td style="vertical-align:middle;"><img src="{_esc(logo)}" width="32" height="32" alt="" style="display:block;border:0;border-radius:9px;"></td>
          <td style="vertical-align:middle;padding-left:10px;font-family:{FONT};font-size:18px;font-weight:600;letter-spacing:-0.02em;color:{INK};">Reliafy</td>
        </tr></table>
      </a>
    </td></tr>
    <tr><td bgcolor="{PANEL}" style="background:{PANEL};border:1px solid {LINE};border-radius:12px;padding:34px 34px 30px;font-family:{FONT};">
      {eyebrow_html}{title_html}{lead_html}{rule}
      {body_html}
      {cta_html}
    </td></tr>
    <tr><td style="padding:22px 8px 0;font-family:{FONT};font-size:12px;line-height:1.6;color:{FAINT};text-align:center;">
      {footer_html}
    </td></tr>
  </table>
</td></tr>
</table>
</body></html>"""
