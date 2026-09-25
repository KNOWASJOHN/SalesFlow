"""
Signaling Module 4 - access-log redaction tests.

The signaling access token travels as a query-string parameter, because a
browser cannot set an Authorization header on a WebSocket upgrade. Anything that
logs the raw request target therefore logs a live bearer token, so uvicorn's
access logger is filtered before startup.

These tests pin that behaviour: the token is scrubbed from plain messages, from
``%s``-style args and from mapping args; surrounding query parameters survive;
messages without a token are untouched; and installing the filter twice attaches
it only once.

Run from the backend project root:
    .\\.venv\\Scripts\\python.exe -m pytest tests/test_logging.py -q
"""

import logging

from app.core.logging import (
    REDACTED,
    AccessTokenRedactionFilter,
    install_access_log_redaction,
)

# A structurally valid JWT; its value is irrelevant, only its leakage matters.
TOKEN = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
    ".eyJzdWIiOiIxMjM0NTY3OC05YWJjLWRlZjAiLCJyb2xlIjoiY3VzdG9tZXIifQ"
    ".c2lnbmF0dXJlLXNpZ25hdHVyZS1zaWduYXR1cmU"
)


def make_record(msg, args=None) -> logging.LogRecord:
    """Build the kind of LogRecord uvicorn's access logger emits."""
    return logging.LogRecord(
        name="uvicorn.access",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg=msg,
        args=args,
        exc_info=None,
    )


def scrub(record: logging.LogRecord) -> str:
    """Run the filter over a record and return the final log line."""
    assert AccessTokenRedactionFilter().filter(record) is True
    return record.getMessage()


def test_redacts_token_from_a_plain_access_log_message():
    record = make_record(f'127.0.0.1:50 - "GET /ws/signaling?access_token={TOKEN} HTTP/1.1" 101')

    scrubbed = scrub(record)

    assert TOKEN not in scrubbed
    assert f"access_token={REDACTED}" in scrubbed
    # The rest of the access-log line must survive - the filter scrubs, it does
    # not drop records.
    assert "GET /ws/signaling" in scrubbed
    assert "101" in scrubbed


def test_redacts_token_from_positional_logging_args():
    """uvicorn formats `%s - "%s %s HTTP/%s" %d`, so the token sits in args."""
    record = make_record(
        '%s - "%s %s HTTP/%s" %d',
        ("127.0.0.1:50", "GET", f"/ws/signaling?access_token={TOKEN}", "1.1", 101),
    )

    scrubbed = scrub(record)

    assert TOKEN not in scrubbed
    assert f"/ws/signaling?access_token={REDACTED}" in scrubbed
    assert "101" in scrubbed


def test_redacts_token_from_mapping_logging_args():
    record = make_record(
        "%(client)s - %(path)s",
        {"client": "127.0.0.1:50", "path": f"/ws/signaling?access_token={TOKEN}"},
    )

    scrubbed = scrub(record)

    assert TOKEN not in scrubbed
    assert REDACTED in scrubbed


def test_redacts_only_the_token_and_keeps_other_query_parameters():
    record = make_record(
        f"/ws/signaling?call_id=42&access_token={TOKEN}&verbose=1"
    )

    scrubbed = scrub(record)

    assert TOKEN not in scrubbed
    assert "call_id=42" in scrubbed
    assert f"access_token={REDACTED}" in scrubbed
    # The delimiter that follows the token must not be swallowed.
    assert "&verbose=1" in scrubbed


def test_redaction_is_case_insensitive_on_the_parameter_name():
    record = make_record(f"/ws/signaling?ACCESS_TOKEN={TOKEN}")

    scrubbed = scrub(record)

    assert TOKEN not in scrubbed
    assert REDACTED in scrubbed


def test_leaves_ordinary_records_untouched():
    record = make_record('127.0.0.1:50 - "GET /health HTTP/1.1" 200')

    assert scrub(record) == '127.0.0.1:50 - "GET /health HTTP/1.1" 200'


def test_install_attaches_exactly_one_filter_across_repeated_calls():
    access_logger = logging.getLogger("uvicorn.access")
    original_filters = list(access_logger.filters)
    access_logger.filters = [
        f for f in original_filters if not isinstance(f, AccessTokenRedactionFilter)
    ]

    try:
        install_access_log_redaction()
        install_access_log_redaction()

        installed = [
            f for f in access_logger.filters if isinstance(f, AccessTokenRedactionFilter)
        ]
        assert len(installed) == 1
    finally:
        access_logger.filters = original_filters


def test_installed_filter_scrubs_records_emitted_through_the_logger():
    """End-to-end through a real handler, not just a hand-built record."""
    install_access_log_redaction()

    captured: list[str] = []

    class Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            captured.append(record.getMessage())

    access_logger = logging.getLogger("uvicorn.access")
    handler = Capture()
    access_logger.addHandler(handler)
    previous_level = access_logger.level
    access_logger.setLevel(logging.INFO)

    try:
        access_logger.info(
            '%s - "%s %s HTTP/%s" %d',
            "127.0.0.1:50",
            "GET",
            f"/ws/signaling?access_token={TOKEN}",
            "1.1",
            101,
        )
    finally:
        access_logger.removeHandler(handler)
        access_logger.setLevel(previous_level)

    assert captured, "the access logger did not emit the record"
    assert TOKEN not in captured[0]
    assert f"access_token={REDACTED}" in captured[0]
