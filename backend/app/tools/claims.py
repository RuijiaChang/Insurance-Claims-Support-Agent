"""Deterministic claim scoring and resolution from remembered hints."""

from dataclasses import dataclass, field
from typing import Literal

from app.data.repo import Claim

W_CASE_ID = 100
W_TYPE = 3
W_STATUS = 3
W_MONTH = 2
W_YEAR = 1
MIN_TOP_SCORE = 3
MIN_MARGIN = 2

_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


@dataclass
class CaseHintsInput:
    case_id: str | None = None
    case_type: str | None = None
    status: str | None = None
    month: int | None = None
    year: int | None = None

    def is_empty(self) -> bool:
        return (
            self.case_id is None
            and self.case_type is None
            and self.status is None
            and self.month is None
            and self.year is None
        )


@dataclass
class ResolveOutcome:
    kind: Literal["unique", "ambiguous", "no_hints", "no_match", "no_claims"]
    case: Claim | None = None
    candidates: list[Claim] = field(default_factory=list)


def _same(a: str | None, b: str) -> bool:
    return a is not None and a.strip().casefold() == b.strip().casefold()


def _score(claim: Claim, hints: CaseHintsInput) -> int:
    score = 0
    if _same(hints.case_id, claim.case_id):
        score += W_CASE_ID
    if _same(hints.case_type, claim.case_type):
        score += W_TYPE
    if _same(hints.status, claim.status):
        score += W_STATUS
    if hints.month is not None and hints.month == claim.created_at.month:
        score += W_MONTH
    if hints.year is not None and hints.year == claim.created_at.year:
        score += W_YEAR
    return score


def score_cases(claims: list[Claim], hints: CaseHintsInput) -> list[tuple[Claim, int]]:
    """Score each claim against the hints, highest first (stable for ties)."""
    scored = [(c, _score(c, hints)) for c in claims]
    return sorted(scored, key=lambda pair: pair[1], reverse=True)


def resolve_case(claims: list[Claim], hints: CaseHintsInput) -> ResolveOutcome:
    if not claims:
        return ResolveOutcome(kind="no_claims")
    if hints.is_empty():
        return ResolveOutcome(kind="no_hints", candidates=list(claims))
    ranked = score_cases(claims, hints)
    top = ranked[0][1]
    second = ranked[1][1] if len(ranked) > 1 else 0
    if top < MIN_TOP_SCORE:
        return ResolveOutcome(kind="no_match", candidates=list(claims))
    if top - second >= MIN_MARGIN:
        return ResolveOutcome(kind="unique", case=ranked[0][0], candidates=[ranked[0][0]])
    return ResolveOutcome(
        kind="ambiguous",
        candidates=[c for c, s in ranked if s >= top - 1],
    )


def claim_summary_line(claim: Claim) -> str:
    d = claim.created_at
    return f"{claim.case_type} claim from {_MONTHS[d.month - 1]} {d.day}, {d.year} ({claim.status})"
