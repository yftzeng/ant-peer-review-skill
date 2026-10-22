"""URL hygiene for anything shown or stored: credentials in query strings are masked."""
from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

SECRET_PARAM = re.compile(r"(?i)^(?:token|.*_token|key|api[-_]?key|apikey|sig|signature|secret|"
                          r"password|passwd|pass|auth|authorization|session|sessionid|code|"
                          r"access[-_]?key|private)$")


def redact(url: str) -> str:
    """Mask the values of credential-like query parameters; keep everything else."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return url
    if not parts.query:
        return url
    pairs = parse_qsl(parts.query, keep_blank_values=True)
    if not any(SECRET_PARAM.match(k) for k, _ in pairs):
        return url
    query = urlencode([(k, "REDACTED" if SECRET_PARAM.match(k) else v) for k, v in pairs])
    return urlunsplit(parts._replace(query=query))
