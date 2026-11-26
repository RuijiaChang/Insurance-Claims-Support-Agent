"""OutputGuard: check every LLM reply for record leakage, ungrounded facts and PII echo.

No LLM calls here. Violations are short machine-readable strings; PII values are
never put into them (only the category).
"""

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation

from dateutil import parser as date_parser

from app.data.repo import FixtureRepo
from app.sop.context import ResponderContext
from app.sop.phases import Phase
from app.sop.state import SessionState
from app.tools.identity import normalize_phone

_GROUNDED_PHASES = frozenset({Phase.PROCESS_CASE, Phase.POST_PROCESS})
_MIN_DOC_NAME_LEN = 6

_NUM = r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?"
_AMOUNT_RE = re.compile(rf"\$\s?(?P<a>{_NUM})|(?P<b>{_NUM})\s*(?:USD|dollars?)\b")
_NUMBER_RE = re.compile(_NUM)
_MONTH = (
    r"Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|June?|July?|Aug(?:ust)?"
    r"|Sept?(?:ember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?"
)
_NAMED_DATE_PATTERN = (
    rf"\b(?P<m>{_MONTH})\.?\s+(?P<d>\d{{1,2}})(?:st|nd|rd|th)?(?:,?\s+(?P<y>\d{{4}}))?\b"
)
_NAMED_DATE_RE = re.compile(_NAMED_DATE_PATTERN, re.IGNORECASE)
_DAY_FIRST_DATE_RE = re.compile(
    rf"\b(?P<d>\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?(?P<m>{_MONTH})\b\.?(?:,?\s+(?P<y>\d{{4}}))?\b",
    re.IGNORECASE,
)
_NUMERIC_DATE_RE = re.compile(r"\b(?P<m>\d{1,2})/(?P<d>\d{1,2})/(?P<y>\d{4}|\d{2})\b")
_MASK_RE = re.compile(r"CL-\d+|POL-\d+|\+\d{10,}", re.IGNORECASE)
_ISO_DATE_RE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_CASE_ID_RE = re.compile(r"CL-\d+", re.IGNORECASE)
_SSN_RE = re.compile(r"(?<!\d)\d{3}[-\s]?\d{2}[-\s]?\d{4}(?!\d)")
_PHONE_RE = re.compile(r"(?<![\w+])(?:\+?1[\s.-]?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}(?!\d)")
# Leap year default so "Feb 29" without a year still parses.
_DEFAULT_YEAR = 2000


@dataclass(frozen=True)
class GuardResult:
    ok: bool
    violations: list[str]


@dataclass(frozen=True)
class _Term:
    category: str
    text: str
    whole_token: bool


def _trim(s: str) -> str:
    return s.rstrip("0").rstrip(".") if "." in s else s


def _amount_forms(raw: str) -> list[str]:
    try:
        q = Decimal(raw)
    except InvalidOperation:
        return []
    if q == 0:
        return []
    forms = [raw, f"{q:.2f}", f"{q:,.2f}"]
    forms += [_trim(f) for f in forms]
    forms = [f for f in forms if f]
    forms += [f"${f}" for f in forms]
    return list(dict.fromkeys(forms))


def _date_forms(d: date) -> list[str]:
    return [d.isoformat(), f"{d:%B} {d.day}, {d.year}"]


def _terms(repo: FixtureRepo) -> list[_Term]:
    out: list[_Term] = []
    for c in repo.claims:
        out.append(_Term("case_id", c.case_id, True))
        for raw in (c.expected_reimbursement_amount, c.allowed_max_amount, c.net_pay, c.net_fee):
            out += [_Term("amount", f, True) for f in _amount_forms(raw)]
        for d in (c.created_at, c.appeal_deadline):
            if d is not None:
                out += [_Term("date", f, True) for f in _date_forms(d)]
        if c.denial_reason:
            out.append(_Term("denial_reason", c.denial_reason, False))
        out += [
            _Term("document", doc, False)
            for doc in c.documents_needed
            if len(doc) >= _MIN_DOC_NAME_LEN
        ]
    for h in repo.policyholders:
        out += [
            _Term("phone", h.phone, False),
            _Term("email", h.email, False),
            _Term("dob", h.dob.isoformat(), False),
        ]
    return out


# Keyed by id(repo); the repo is kept in the value so a recycled id cannot hit stale data.
_CACHE: dict[int, tuple[FixtureRepo, list[_Term]]] = {}


def _cached_terms(repo: FixtureRepo) -> list[_Term]:
    hit = _CACHE.get(id(repo))
    if hit is not None and hit[0] is repo:
        return hit[1]
    terms = _terms(repo)
    _CACHE[id(repo)] = (repo, terms)
    return terms


def sensitive_terms(repo: FixtureRepo) -> set[str]:
    return {t.text for t in _cached_terms(repo)}


def _contains_token(haystack: str, term: str) -> bool:
    return re.search(rf"(?<!\w){re.escape(term)}(?!\w|[.,]\d)", haystack, re.IGNORECASE) is not None


def _leak_violations(reply: str, user_corpus: str, repo: FixtureRepo) -> list[str]:
    reply_l = reply.lower()
    corpus_l = user_corpus.lower()
    found: list[str] = []
    for t in _cached_terms(repo):
        if t.category in {"date", "dob", "amount"}:
            continue  # Compare typed values below so equivalent formats cannot evade the gate.
        term_l = t.text.lower()
        if _contains_token(user_corpus, t.text) if t.whole_token else term_l in corpus_l:
            continue
        hit = _contains_token(reply, t.text) if t.whole_token else term_l in reply_l
        if hit:
            found.append(f"leak:{t.text}" if t.category == "case_id" else f"leak:{t.category}")
    record_dates = {
        d
        for claim in repo.claims
        for d in (claim.created_at, claim.appeal_deadline)
        if d is not None
    }
    record_dobs = {holder.dob for holder in repo.policyholders}
    user_dates = {d for _, d, has_year in _extract_dates(user_corpus) if has_year}
    for _, d, has_year in _extract_dates(reply):
        if has_year and d not in user_dates:
            if d in record_dates:
                found.append("leak:date")
            if d in record_dobs:
                found.append("leak:dob")
    record_amounts = {
        Decimal(raw)
        for claim in repo.claims
        for raw in (
            claim.expected_reimbursement_amount,
            claim.allowed_max_amount,
            claim.net_pay,
            claim.net_fee,
        )
        if Decimal(raw) != 0
    }
    if (_whitelist_amounts(reply) - _whitelist_amounts(user_corpus)) & record_amounts:
        found.append("leak:amount")
    return found


def _build_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _extract_dates(text: str) -> list[tuple[re.Match[str], date, bool]]:
    """Every date expression in the text as (match, date, has_year)."""
    out: list[tuple[re.Match[str], date, bool]] = []
    for m in _ISO_DATE_RE.finditer(text):
        d = _build_date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if d is not None:
            out.append((m, d, True))
    for m in _NUMERIC_DATE_RE.finditer(text):
        year = int(m.group("y"))
        d = _build_date(year + 2000 if year < 100 else year, int(m.group("m")), int(m.group("d")))
        if d is not None:
            out.append((m, d, True))
    for pattern in (_NAMED_DATE_RE, _DAY_FIRST_DATE_RE):
        for m in pattern.finditer(text):
            month = date_parser.parse(f"{m.group('m')} 1").month
            year_text = m.group("y")
            d = _build_date(
                int(year_text) if year_text else _DEFAULT_YEAR, month, int(m.group("d"))
            )
            if d is not None:
                out.append((m, d, year_text is not None))
    return out


def _whitelist_dates(text: str) -> set[date]:
    return {d for _, d, _ in _extract_dates(text)}


def _whitelist_amounts(text: str) -> set[Decimal]:
    # Mask dates, ids and phone numbers so their digits are not read as amounts.
    for m, _, _ in sorted(_extract_dates(text), key=lambda t: -t[0].start()):
        text = text[: m.start()] + " " + text[m.end() :]
    text = _PHONE_RE.sub(" ", _MASK_RE.sub(" ", text))
    return {Decimal(m.group(0).replace(",", "")) for m in _NUMBER_RE.finditer(text)}


def _grounding_violations(reply: str, whitelist: str) -> list[str]:
    found: list[str] = []
    allowed_amounts = _whitelist_amounts(whitelist)
    for m in _AMOUNT_RE.finditer(reply):
        value = Decimal((m.group("a") or m.group("b")).replace(",", ""))
        if value not in allowed_amounts:
            found.append(f"ungrounded_amount:{m.group(0).strip()}")

    allowed_dates = _whitelist_dates(whitelist)
    allowed_month_days = {(d.month, d.day) for d in allowed_dates}
    for m, d, has_year in _extract_dates(reply):
        ok = d in allowed_dates if has_year else (d.month, d.day) in allowed_month_days
        if not ok:
            found.append(f"ungrounded_date:{m.group(0)}")

    allowed_ids = {c.upper() for c in _CASE_ID_RE.findall(whitelist.upper())}
    for case_id in _CASE_ID_RE.findall(reply):
        if case_id.upper() not in allowed_ids:
            found.append(f"ungrounded_case_id:{case_id}")
    return found


def _pii_violations(reply: str, repo: FixtureRepo) -> list[str]:
    found: list[str] = []
    if _SSN_RE.search(reply):
        found.append("pii_echo:ssn")
    holder_phones = {
        p
        for h in repo.policyholders
        for raw in (h.phone, *h.phone_aliases)
        if (p := normalize_phone(raw)) is not None
    }
    if any(normalize_phone(m.group(0)) in holder_phones for m in _PHONE_RE.finditer(reply)):
        found.append("pii_echo:phone")
    reply_l = reply.lower()
    if any(e.lower() in reply_l for h in repo.policyholders for e in (h.email, *h.email_aliases)):
        found.append("pii_echo:email")
    return found


def check_reply(
    reply: str, state: SessionState, rctx: ResponderContext, repo: FixtureRepo
) -> GuardResult:
    violations: list[str] = []
    if not state.access_granted:
        user_corpus = "\n".join(
            [*(m.text for m in state.transcript if m.role == "user"), rctx.user_text]
        )
        violations += _leak_violations(reply, user_corpus, repo)
    if rctx.phase in _GROUNDED_PHASES:
        violations += _grounding_violations(reply, rctx.whitelist_text)
    violations += _pii_violations(reply, repo)
    unique = list(dict.fromkeys(violations))
    return GuardResult(ok=not unique, violations=unique)
