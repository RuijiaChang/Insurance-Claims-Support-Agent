"""Identity normalization and N-of-5 verification (pure functions, no I/O)."""

import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal

import phonenumbers
from dateutil import parser as date_parser
from rapidfuzz import fuzz

from app.data.repo import Policyholder, Representative

IdentityField = Literal["full_name", "dob", "phone", "email", "id_last4"]
IDENTITY_FIELDS: tuple[IdentityField, ...] = ("full_name", "dob", "phone", "email", "id_last4")

Relationship = Literal["child", "parent", "spouse", "sibling", "other"]

_RELATIONSHIPS: dict[str, Relationship] = {
    "child": "child",
    "son": "child",
    "daughter": "child",
    "kid": "child",
    "parent": "parent",
    "mom": "parent",
    "mother": "parent",
    "mum": "parent",
    "dad": "parent",
    "father": "parent",
    "spouse": "spouse",
    "wife": "spouse",
    "husband": "spouse",
    "partner": "spouse",
    "sibling": "sibling",
    "brother": "sibling",
    "sister": "sibling",
    "other": "other",
}


def normalize_name(s: str) -> str:
    cleaned = re.sub(r"[^\w\s]", " ", s.casefold())
    return " ".join(cleaned.split())


_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_SENTINELS = (datetime(2000, 1, 1), datetime(2001, 2, 2))


def _parse_full_date(s: str, dayfirst: bool) -> date | None:
    """Parse a complete date; reject partial input and never return a future date."""
    try:
        a, b = (date_parser.parse(s, dayfirst=dayfirst, default=d) for d in _SENTINELS)
    except (ValueError, OverflowError):
        return None
    if a != b:  # a component was missing and filled from the default
        return None
    d = a.date()
    if d > date.today():  # two-digit years resolve into the past for a date of birth
        try:
            d = d.replace(year=d.year - 100)
        except ValueError:  # Feb 29
            d = d.replace(year=d.year - 100, day=28)
    return d


def parse_dob(s: str) -> list[date]:
    """Parse a date of birth; returns two candidates when month/day order is ambiguous."""
    s = s.strip()
    passes = (False,) if _ISO_DATE.match(s) else (False, True)
    results: list[date] = []
    for dayfirst in passes:
        d = _parse_full_date(s, dayfirst)
        if d is not None and d not in results:
            results.append(d)
    return results


def normalize_phone(s: str) -> str | None:
    try:
        num = phonenumbers.parse(s, "US")
    except phonenumbers.NumberParseException:
        return None
    # A well-formed number that isn't an assigned one (e.g. 555-111-2222) still counts as
    # a provided detail; it simply won't match anyone, so it fails verification visibly.
    if not phonenumbers.is_possible_number(num):
        return None
    return phonenumbers.format_number(num, phonenumbers.PhoneNumberFormat.E164)


def normalize_email(s: str) -> str:
    return s.strip().casefold()


_POLICY_NUMBER = re.compile(r"POL-?(\d+)")


def normalize_policy_number(s: str) -> str:
    """Canonical policy number: ``POL9921`` / ``pol-9921`` -> ``POL-9921``."""
    key = s.strip().upper()
    m = _POLICY_NUMBER.fullmatch(key)
    return f"POL-{m.group(1)}" if m else key


def normalize_last4(s: str) -> str | None:
    digits = re.sub(r"\D", "", s)
    return digits if len(digits) == 4 else None


def normalize_relationship(s: str) -> Relationship | None:
    return _RELATIONSHIPS.get(s.strip().casefold())


def _name_matches(value: str, candidates: list[str], threshold: int) -> bool:
    v = normalize_name(value)
    if not v:
        return False
    return any(fuzz.token_sort_ratio(v, normalize_name(c)) >= threshold for c in candidates)


def field_matches(
    field: IdentityField, values: list[str], holder: Policyholder, name_threshold: int
) -> bool:
    """True if any provided value matches the holder's record for this field."""
    for value in values:
        if field == "full_name":
            ok = _name_matches(value, [holder.name, *holder.name_aliases], name_threshold)
        elif field == "dob":
            ok = holder.dob in parse_dob(value)
        elif field == "phone":
            n = normalize_phone(value)
            known = {normalize_phone(p) for p in [holder.phone, *holder.phone_aliases]}
            ok = n is not None and n in known
        elif field == "email":
            known_emails = {normalize_email(e) for e in [holder.email, *holder.email_aliases]}
            ok = normalize_email(value) in known_emails
        else:
            n4 = normalize_last4(value)
            ok = n4 is not None and n4 == normalize_last4(holder.id_last4)
        if ok:
            return True
    return False


def _provided(
    values: dict[IdentityField, list[str]], refused: set[IdentityField]
) -> list[IdentityField]:
    return [f for f in IDENTITY_FIELDS if values.get(f) and f not in refused]


def find_candidates(
    values: dict[IdentityField, list[str]],
    policy_number: str | None,
    holders: list[Policyholder],
    name_threshold: int,
) -> list[Policyholder]:
    """Locate candidate holders: by policy number if given, else by any matching field."""
    if policy_number:
        key = normalize_policy_number(policy_number)
        by_policy = [h for h in holders if normalize_policy_number(h.policy_number) == key]
        if by_policy:
            return by_policy
    fields = _provided(values, set())
    return [
        h for h in holders if any(field_matches(f, values[f], h, name_threshold) for f in fields)
    ]


@dataclass(frozen=True)
class VerifyOutcome:
    status: Literal["insufficient", "pass", "fail"]
    party_id: str | None
    matched_fields: frozenset[IdentityField]


def verify(
    values: dict[IdentityField, list[str]],
    refused: set[IdentityField],
    policy_number: str | None,
    holders: list[Policyholder],
    name_threshold: int,
    min_fields: int,
) -> VerifyOutcome:
    provided = _provided(values, refused)
    if len(provided) < min_fields:
        return VerifyOutcome("insufficient", None, frozenset())
    usable = {f: values[f] for f in provided}
    for holder in find_candidates(usable, policy_number, holders, name_threshold):
        matched = frozenset(
            f for f in provided if field_matches(f, usable[f], holder, name_threshold)
        )
        mismatched = len(provided) - len(matched)
        if len(matched) >= min_fields and mismatched == 0:
            return VerifyOutcome("pass", holder.party_id, matched)
    return VerifyOutcome("fail", None, frozenset())


def match_representative(
    rep_name: str | None,
    relationship: Relationship | None,
    party_id: str,
    reps: list[Representative],
    name_threshold: int,
) -> bool:
    if not rep_name or relationship is None:
        return False
    for rep in reps:
        if rep.buyer_party_id != party_id:
            continue
        if normalize_relationship(rep.relationship) != relationship:
            continue
        if _name_matches(rep_name, [rep.rep_name], name_threshold):
            return True
    return False
