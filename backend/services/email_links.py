"""Campaign (UTM) tags on the links in our own emails (#269).

Every link to the site in an update or lifecycle email gets
``utm_source=email&utm_medium=<kind>&utm_campaign=<name>``, so the site's
first-party analytics (which keeps ``utm_*`` for the rest of the visit, see
``frontend/src/telemetry.js``) can count what each email brought in.

Left alone: links to other sites, ``mailto:``, the unsubscribe links (a
token URL, and nothing to measure), and any link that already carries a
``utm_*`` tag. An existing query string and ``#anchor`` are kept as they are;
the tags go after the query and before the anchor.
"""

from __future__ import annotations

import html as html_lib
import re
from urllib.parse import urlencode, urlsplit

from backend import config

SOURCE = "email"
# Paths whose links must never change: the unsubscribe page and its API.
_UNTOUCHED_PATHS = ("/unsubscribe", "/api/email/unsubscribe", "/api/email/resubscribe")
_OWN_HOSTS = {"reliafy.com", "www.reliafy.com"}


def _own_hosts() -> set[str]:
    hosts = set(_OWN_HOSTS)
    if config.PUBLIC_BASE_URL:
        host = (urlsplit(config.PUBLIC_BASE_URL).hostname or "").lower()
        if host:
            hosts.add(host)
    return hosts


def should_tag(url: str) -> bool:
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    if parts.scheme not in ("http", "https"):
        return False
    if (parts.hostname or "").lower() not in _own_hosts():
        return False
    path = parts.path.rstrip("/") or "/"
    if path in _UNTOUCHED_PATHS:
        return False
    return not re.search(r"(^|&)utm_[a-z]+=", parts.query)


def tag_url(url: str, *, medium: str, campaign: str) -> str:
    """``url`` with the campaign tags added, or unchanged (see module doc)."""
    if not should_tag(url):
        return url
    base, hash_, fragment = url.partition("#")
    tags = urlencode({"utm_source": SOURCE, "utm_medium": medium, "utm_campaign": campaign})
    if "?" in base:
        sep = "" if base.endswith(("?", "&")) else "&"
    else:
        sep = "?"
    return f"{base}{sep}{tags}{hash_}{fragment}"


_HREF_RE = re.compile(r'(href=")([^"]*)(")', re.IGNORECASE)
# A bare URL in plain text, without trailing sentence punctuation or a
# closing bracket that belongs to the prose around it.
_TEXT_URL_RE = re.compile(r"https?://[^\s<>\"()]*[^\s<>\"().,;:!?'\]]")


def tag_html(html: str, *, medium: str, campaign: str) -> str:
    """Tag every ``href="..."`` in an HTML email (attribute values are
    unescaped, tagged, and escaped again)."""
    def repl(m: re.Match) -> str:
        url = html_lib.unescape(m.group(2))
        tagged = tag_url(url, medium=medium, campaign=campaign)
        if tagged == url:
            return m.group(0)
        return f"{m.group(1)}{html_lib.escape(tagged, quote=True)}{m.group(3)}"
    return _HREF_RE.sub(repl, html)


def tag_text(text: str, *, medium: str, campaign: str) -> str:
    """Tag every URL in a plain-text email."""
    return _TEXT_URL_RE.sub(lambda m: tag_url(m.group(0), medium=medium, campaign=campaign), text)
