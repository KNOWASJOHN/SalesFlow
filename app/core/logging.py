"""
Access-log redaction for signaling credentials (Module 4).

Browsers cannot set custom headers on a WebSocket upgrade, so the signaling
access token travels as a query-string parameter
(``/ws/signaling?access_token=<jwt>``). Uvicorn's access logger writes the
wholesale request target, which would otherwise leave a live bearer token in
every access-log line and in any log aggregator downstream of it.

``install_access_log_redaction()`` attaches a filter to ``uvicorn.access`` that
rewrites ``access_token=...`` to ``access_token=[REDACTED]`` before the record
is formatted. The filter mutates ``record.msg`` / ``record.args`` in place and
always returns True, so it scrubs records without ever dropping them.
"""

import logging
import re
from typing import Any

# Matches `?access_token=...` or `&access_token=...` up to the next delimiter,
# so it also redacts the token when it is not the first query parameter.
_ACCESS_TOKEN_PATTERN = re.compile(r"([?&]access_token=)[^&\s\"]+", re.IGNORECASE)

REDACTED = "[REDACTED]"


def _redact(value: Any) -> Any:
    """
    Return ``value`` with every signaling token replaced by ``[REDACTED]``.

    Log records arrive in several shapes — a plain message string, a positional
    args tuple (``%s``-style logging), or a mapping (``%(name)s``-style) — so
    each container is walked rather than stringified and regexed once.
    """
    if isinstance(value, str):
        return _ACCESS_TOKEN_PATTERN.sub(rf"\g<1>{REDACTED}", value)

    if isinstance(value, tuple):
        return tuple(_redact(item) for item in value)

    if isinstance(value, dict):
        return {key: _redact(item) for key, item in value.items()}

    return value


class AccessTokenRedactionFilter(logging.Filter):
    """Keep query-string signaling tokens out of log records."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = _redact(record.msg)
        record.args = _redact(record.args)
        return True


def install_access_log_redaction() -> None:
    """
    Attach :class:`AccessTokenRedactionFilter` to uvicorn's access logger.

    Idempotent: repeated calls (reload, multiple imports, tests) attach the
    filter at most once so records are never scrubbed twice.
    """
    access_logger = logging.getLogger("uvicorn.access")

    already_installed = any(
        isinstance(existing, AccessTokenRedactionFilter)
        for existing in access_logger.filters
    )

    if not already_installed:
        access_logger.addFilter(AccessTokenRedactionFilter())
