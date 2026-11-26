"""Key redaction must not break third-party formatters that unpack ``record.args``."""

import logging

from uvicorn.logging import AccessFormatter

from app.api import install_key_redaction

KEY = "sk-redact-me-0123456789abcdef"


class _Capture(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


def _logger(name: str) -> tuple[logging.Logger, _Capture]:
    log = logging.getLogger(name)
    log.propagate = False
    log.setLevel(logging.DEBUG)
    cap = _Capture()
    log.handlers = [cap]
    return log, cap


def test_uvicorn_access_record_still_formats_after_redaction() -> None:
    install_key_redaction()
    log, cap = _logger("test.redaction.uvicorn.access")
    log.info('%s - "%s %s HTTP/%s" %d', "127.0.0.1:1", "GET", "/x", "1.1", 200)
    record = cap.records[0]
    assert record.args == ("127.0.0.1:1", "GET", "/x", "1.1", 200)
    out = AccessFormatter(fmt="%(client_addr)s %(request_line)s %(status_code)s").format(record)
    assert "GET /x" in out and "200" in out


def test_args_redacted_in_place_without_changing_shape() -> None:
    install_key_redaction()
    log, cap = _logger("test.redaction.args")
    log.info("key %s n=%d", KEY, 3)
    log.info("dict %(k)s", {"k": KEY, "n": 1})
    log.info("list %s", [KEY, 2])
    tup, dct, lst = cap.records
    assert tup.args == ("sk-***", 3)
    assert dct.args == {"k": "sk-***", "n": 1}
    assert lst.getMessage() == "list ['sk-***', 2]"
    assert all(KEY not in r.getMessage() for r in cap.records)


def test_exception_text_is_redacted_but_exc_info_kept() -> None:
    install_key_redaction()
    log, cap = _logger("test.redaction.exc")
    try:
        raise RuntimeError(f"bad {KEY}")
    except RuntimeError:
        log.exception("failed with %s", KEY)
    record = cap.records[0]
    assert record.exc_info is not None
    out = logging.Formatter().format(record)
    assert KEY not in out
    assert "RuntimeError: bad sk-***" in out and "failed with sk-***" in out


def test_malformed_args_fall_back_to_redacted_message() -> None:
    install_key_redaction()
    log, cap = _logger("test.redaction.malformed")
    log.info("two %s %s", KEY)  # noqa: PLE1206 - deliberately malformed: one arg, two slots
    record = cap.records[0]
    assert record.args == ()
    assert KEY not in record.getMessage()
