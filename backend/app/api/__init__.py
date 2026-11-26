"""REST API package, plus the app-wide log filter that masks API keys.

A ``logging.Filter`` on the root logger only sees records logged *on* the root logger
(not ones propagated from child loggers), so ``install_key_redaction`` also attaches it
to the root handlers and wraps the record factory: every record from every logger is
redacted once, at creation.

Redaction keeps each record's shape: ``args`` are redacted element-wise (formatters such as
uvicorn's ``AccessFormatter`` unpack them), and ``exc_info`` is kept while the formatted,
redacted traceback is pre-set as ``exc_text`` (which ``Formatter.format`` prefers).
"""

import logging
import re
import traceback
from collections.abc import Mapping
from typing import Any

_KEY_RE = re.compile(r"sk-[A-Za-z0-9_-]{8,}")
_installed = False


def redact(text: str) -> str:
    return _KEY_RE.sub("sk-***", text)


def _redact_value(value: Any) -> Any:
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    if isinstance(value, tuple):
        return tuple(_redact_value(v) for v in value)
    if isinstance(value, list):
        return [_redact_value(v) for v in value]
    if isinstance(value, Mapping):
        return {k: _redact_value(v) for k, v in value.items()}
    # Any other object (e.g. an exception) only changes if its text actually holds a key.
    try:
        text = str(value)
    except Exception:  # noqa: BLE001 - a broken __str__ must not break logging
        return value
    return redact(text) if _KEY_RE.search(text) else value


class KeyRedactionFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if record.__dict__.get("_keys_redacted"):
            return True
        if isinstance(record.msg, str):
            record.msg = redact(record.msg)
        if record.args:
            original = record.args
            record.args = _redact_value(original)
            try:
                record.getMessage()
            except (TypeError, ValueError, KeyError):  # malformed args: flatten to text
                record.args = ()
                record.msg = redact(f"{record.msg} {original!r}")
        if record.exc_info and not record.exc_text:
            text = "".join(traceback.format_exception(*record.exc_info))
            record.exc_text = redact(text.rstrip("\n"))
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
