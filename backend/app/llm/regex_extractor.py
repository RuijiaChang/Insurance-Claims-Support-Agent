"""Deterministic regex extraction: fallback when the LLM fails, and override for format fields."""

import re
from dataclasses import dataclass

from app.tools.identity import normalize_email, normalize_phone

_MONTHS = (
    r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|"
    r"Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
)
_DOB_PATTERNS = [
    re.compile(r"(?<![\d/-])\d{4}[-/]\d{1,2}[-/]\d{1,2}(?![\d/-])"),
    re.compile(r"(?<![\d/-])\d{1,2}[-/]\d{1,2}[-/]\d{2,4}(?![\d/-])"),
    re.compile(rf"\b{_MONTHS}\.?\s+\d{{1,2}}(?:st|nd|rd|th)?,?\s+\d{{4}}\b", re.IGNORECASE),
    re.compile(rf"\b\d{{1,2}}(?:st|nd|rd|th)?\s+{_MONTHS}\.?,?\s+\d{{4}}\b", re.IGNORECASE),
]
_PHONE = re.compile(r"(?<![\w-])(?:\+?1[\s.-]?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}(?![\w-])")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_LAST4_KEYWORD = re.compile(r"last\s+four|last\s+4|ssn|social|national\s+id|\bid\b", re.IGNORECASE)
_YEAR_LIKE = re.compile(r"(?:19|20)\d\d$")
_KEYWORD_FILLER = re.compile(r"[\s:=#,-]*(?:(?:is|are|digits|last|four|4|number|of)\b[\s:=#,-]*)*")
_LAST4_WINDOW = 30
_LAST4_DIGITS = re.compile(r"(?<![\w-])\d{4}(?![\w]|-\d)")
_POLICY = re.compile(r"\bPOL-?\d+\b", re.IGNORECASE)
_CASE = re.compile(r"\bCL-\d+\b", re.IGNORECASE)


@dataclass
class RegexHits:
    dob_raw: str | None = None
    phone: str | None = None  # E.164
    email: str | None = None  # lowercase
    id_last4: str | None = None
    policy_number: str | None = None
    case_id: str | None = None


def date_candidates(text: str) -> list[str]:
    """Every date-shaped substring of the text, in any supported format."""
    return [m.group(0) for pattern in _DOB_PATTERNS for m in pattern.finditer(text)]


def phone_candidates(text: str) -> list[str]:
    """Every phone-shaped substring of the text."""
    return [m.group(0) for m in _PHONE.finditer(text)]


def _find_dob(text: str) -> str | None:
    """Return the last DOB-shaped match by position, so later corrections win."""
    matches = [m for pattern in _DOB_PATTERNS for m in pattern.finditer(text)]
    return max(matches, key=lambda m: m.start()).group(0) if matches else None


def _find_phone(text: str) -> str | None:
    for m in _PHONE.finditer(text):
        phone = normalize_phone(m.group(0))
        if phone:
            return phone
    return None


def _mask_non_last4_spans(text: str) -> str:
    """Blank out dates, phone numbers and policy/case ids so their digits are never last4."""
    chars = list(text)
    for pattern in [*_DOB_PATTERNS, _PHONE, _POLICY, _CASE]:
        for m in pattern.finditer(text):
            chars[m.start() : m.end()] = " " * (m.end() - m.start())
    return "".join(chars)


def _find_last4(text: str) -> str | None:
    masked = _mask_non_last4_spans(text)
    for kw in _LAST4_KEYWORD.finditer(masked):
        strong = kw.group(0).lower() != "id"
        start = kw.end()
        for m in _LAST4_DIGITS.finditer(masked, start, start + _LAST4_WINDOW):
            digits = m.group(0)
            if _YEAR_LIKE.match(digits) and not (
                strong and _KEYWORD_FILLER.fullmatch(masked[start : m.start()])
            ):
                continue
            return digits
    return None


def _upper_match(pattern: re.Pattern[str], text: str) -> str | None:
    m = pattern.search(text)
    return m.group(0).upper() if m else None


def extract_regex(text: str) -> RegexHits:
    email = _EMAIL.search(text)
    return RegexHits(
        dob_raw=_find_dob(text),
        phone=_find_phone(text),
        email=normalize_email(email.group(0)) if email else None,
        id_last4=_find_last4(text),
        policy_number=_upper_match(_POLICY, text),
        case_id=_upper_match(_CASE, text),
    )
