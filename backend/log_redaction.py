"""Strip link tokens from text that is logged or stored.

Upload links (``?t=``), email-preference links (``?t=``), share-link unlock
tokens (``?unlock=``) and public share links (``/api/public/<token>``,
``/p/<token>``) each carry their link's only credential. Access-log lines,
telemetry fields and stored page paths go through :func:`redact_secrets`.
"""

from __future__ import annotations

import re

_SECRET_PATTERNS = (
    (re.compile(r"([?&]t=)[^&\s\"'#]+"), r"\1[redacted]"),
    (re.compile(r"([?&]unlock=)[^&\s\"'#]+"), r"\1[redacted]"),
    (re.compile(r"(/api/public/)[^/?#\s\"']+"), r"\1[redacted]"),
    (re.compile(r"((?:^|[\s\"'(=]|https?://[^/\s\"']+)/p/)[^/?#\s\"']+"), r"\1[redacted]"),
)


def has_secret(text: str) -> bool:
    return any(p.search(text) for p, _ in _SECRET_PATTERNS)


def redact_secrets(text: str) -> str:
    """``text`` with link tokens replaced by ``[redacted]``."""
    for pattern, repl in _SECRET_PATTERNS:
        text = pattern.sub(repl, text)
    return text
