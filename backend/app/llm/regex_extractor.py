"""Deterministic regex extraction: fallback when the LLM fails, and override for format fields."""

import re
from dataclasses import dataclass

from app.tools.identity import normalize_email, normalize_phone

_MONTHS = (
    r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|"
    r"Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
)
_DOB_PATTERNS = [
    re.compile(r"(?<![\d/-])\d{4}-\d{1,2}-\d{1,2}(?![\d/-])"),
    re.compile(r"(?<![\d/])\d{1,2}/\d{1,2}/\d{2,4}(?![\d/])"),
    re.compile(rf"\b{_MONTHS}\.?\s+\d{{1,2}}(?:st|nd|rd|th)?,?\s+\d{{4}}\b", re.IGNORECASE),
    re.compile(rf"\b\d{{1,2}}(?:st|nd|rd|th)?\s+{_MONTHS}\.?,?\s+\d{{4}}\b", re.IGNORECASE),
]
_PHONE = re.compile(r"(?<![\w-])(?:\+?1[\s.-]?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}(?![\w-])")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_LAST4_KEYWORD = re.compile(r"last\s+four|last\s+4|ssn|social|national\s+id|\bid\b", re.IGNORECASE)
_LAST4_WINDOW = 30
_LAST4_DIGITS = re.compile(r"(?<![\w-])\d{4}(?![\w]|-\d)")
_POLICY = re.compile(r"\bPOL-\d+\b", re.IGNORECASE)
_CASE = re.compile(r"\bCL-\d+\b", re.IGNORECASE)


@dataclass
class RegexHits:
    dob_raw: str | None = None
    phone: str | None = None  # E.164
    email: str | None = None  # lowercase
    id_last4: str | None = None
    policy_number: str | None = None
    case_id: str | None = None


def _find_dob(text: str) -> str | None:
    for pattern in _DOB_PATTERNS:
        m = pattern.search(text)
        if m:
            return m.group(0)
    return None


def _find_phone(text: str) -> str | None:
    for m in _PHONE.finditer(text):
        phone = normalize_phone(m.group(0))
        if phone:
            return phone
    return None


def _find_last4(text: str) -> str | None:
    for kw in _LAST4_KEYWORD.finditer(text):
        window = text[kw.end() : kw.end() + _LAST4_WINDOW]
        m = _LAST4_DIGITS.search(window)
        if m:
            return m.group(0)
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
