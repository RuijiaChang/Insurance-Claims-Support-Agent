"""REST API package, plus the app-wide log filter that masks API keys.

A ``logging.Filter`` on the root logger only sees records logged *on* the root logger
(not ones propagated from child loggers), so ``install_key_redaction`` also attaches it
to the root handlers and wraps the record factory: every record from every logger is
redacted once, at creation, including its formatted exception text.
"""

import logging
import re
import traceback
from typing import Any

_KEY_RE = re.compile(r"sk-[A-Za-z0-9_-]{8,}")
_installed = False


def redact(text: str) -> str:
    return _KEY_RE.sub("sk-***", text)


class KeyRedactionFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if record.__dict__.get("_keys_redacted"):
            return True
        try:
            message = record.getMessage()
        except (TypeError, ValueError, KeyError):  # malformed args: keep the raw template
            message = str(record.msg)
        record.msg = redact(message)
        record.args = None
        if record.exc_info:
            text = "".join(traceback.format_exception(*record.exc_info))
            record.exc_text = redact(text.rstrip("\n"))
            record.exc_info = None
        elif record.exc_text:
            record.exc_text = redact(record.exc_text)
        record.__dict__["_keys_redacted"] = True
        return True


def install_key_redaction() -> None:
    """Idempotently install key redaction for all loggers."""
    global _installed
    flt = KeyRedactionFilter()
    root = logging.getLogger()
    for target in (root, *root.handlers):
        if not any(isinstance(f, KeyRedactionFilter) for f in target.filters):
            target.addFilter(flt)
    if _installed:
        return
    _installed = True
    previous = logging.getLogRecordFactory()

    def factory(*args: Any, **kwargs: Any) -> logging.LogRecord:
        record = previous(*args, **kwargs)
        flt.filter(record)
        return record

    logging.setLogRecordFactory(factory)
