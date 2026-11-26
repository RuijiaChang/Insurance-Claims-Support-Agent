"""Fixture-grounded guidance matching, document-name mapping and deadline facts."""

from dataclasses import dataclass
from datetime import date
from typing import Any, Literal

from rapidfuzz import fuzz

from app.data.repo import Claim, FixtureRepo

GuidanceTopic = Literal[
    "missing_required_material_alternatives",
    "submission_timing",
    "processing_time_after_submission",
    "submission_method",
    "file_format_requirements",
    "receipt_confirmation",
]

Intent = Literal[
    "denial_question",
    "status_inquiry",
    "document_submission",
    "next_steps",
    "general_claim_question",
    "payment_question",
]

DOC_ALIASES: dict[str, str] = {
    "pathology report": "original pathology report",
    "office note": "treating provider office note",
    "repair estimate": "repair estimate",
    "accident photos": "supplemental accident scene photos",
    "accident scene photos": "supplemental accident scene photos",
}


def canonical_doc(name: str, keys: list[str], threshold: int) -> str | None:
    """Map a claim document name to a guideline key, or None if nothing is close enough."""
    lowered = name.strip().lower()
    alias = DOC_ALIASES.get(lowered)
    if alias is not None:
        return alias
    best: str | None = None
    best_score = 0.0
    for key in keys:
        score = fuzz.partial_ratio(lowered, key.lower())
        if score >= threshold and score > best_score:
            best, best_score = key, score
    return best


def documents_phrase(docs: list[str]) -> str:
    items = [f"the {d}" for d in docs]
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    if len(items) == 2:
        return f"{items[0]} and {items[1]}"
    return ", ".join(items[:-1]) + f", and {items[-1]}"


def _en(node: dict[str, Any]) -> str:
    return str(node["en"])


@dataclass
class DocRequirements:
    default: str
    case_type: str | None
    per_document: dict[str, str]


def document_requirements(repo: FixtureRepo, claim: Claim, threshold: int) -> DocRequirements:
    g = repo.guideline
    keys = list(g["document_guidance"])
    per_document: dict[str, str] = {}
    for doc in claim.documents_needed:
        key = canonical_doc(doc, keys, threshold)
        if key is not None:
            per_document[doc] = _en(g["document_guidance"][key])
    ct = g["case_type_guidance"].get(claim.case_type)
    return DocRequirements(
        default=_en(g["default_guidance"]),
        case_type=_en(ct) if ct else None,
        per_document=per_document,
    )


def document_alternatives(
    repo: FixtureRepo, claim: Claim, document: str | None, threshold: int
) -> dict[str, str]:
    alts = repo.guideline["document_alternative_guidance"]
    keys = [k for k in alts if k != "default"]
    docs = claim.documents_needed if document is None else [document]
    result: dict[str, str] = {}
    for doc in docs:
        key = canonical_doc(doc, keys, threshold)
        if key is not None:
            result[doc] = _en(alts[key])
    result["default"] = _en(alts["default"])
    return result


@dataclass
class FollowupResult:
    kind: Literal["matched", "fallback", "no_specific_guidance"]
    topic: GuidanceTopic | None
    text: str | None


def _longest_hit(question: str, phrases: list[str]) -> int:
    """Length of the longest phrase occurrence not immediately followed by 'ago'; 0 if none."""
    best = 0
    for phrase in phrases:
        start = question.find(phrase)
        while start != -1:
            end = start + len(phrase)
            if not question[end:].lstrip().startswith("ago"):
                best = max(best, len(phrase))
                break
            start = question.find(phrase, start + 1)
    return best


def _render(repo: FixtureRepo, claim: Claim, entry: dict[str, Any]) -> str:
    settings = repo.guideline["claim_followup_settings"]
    return str(entry["en"]).format(
        case_id=claim.case_id,
        documents=documents_phrase(claim.documents_needed),
        average_processing_time_after_submission=_en(
            settings["average_processing_time_after_submission"]
        ),
    )


def match_followup(
    repo: FixtureRepo,
    claim: Claim,
    question: str,
    turn_intent: Intent | None,
    topic: GuidanceTopic | None,
) -> FollowupResult:
    q = question.lower()
    candidates = [
        e
        for e in repo.guideline["claim_followup_guidance"]
        if not e.get("requires_documents") or claim.documents_needed
    ]
    best: dict[str, Any] | None = None
    best_key = (0, 0)
    for entry in candidates:
        length = _longest_hit(q, [p.lower() for p in entry.get("match_any", [])])
        if length == 0:
            continue
        key = (length, 1 if turn_intent and turn_intent in entry.get("intent_hints", []) else 0)
        if key > best_key:
            best, best_key = entry, key
    if best is None and topic is not None:
        best = next((e for e in candidates if e["topic"] == topic), None)
    if best is not None:
        return FollowupResult("matched", best["topic"], _render(repo, claim, best))
    if claim.documents_needed:
        return FollowupResult("fallback", None, _en(repo.guideline["claim_followup_fallback"]))
    return FollowupResult("no_specific_guidance", None, None)


@dataclass
class DeadlineFact:
    deadline: date
    days_left: int
    passed: bool


def deadline_fact(claim: Claim, today: date) -> DeadlineFact | None:
    if claim.appeal_deadline is None:
        return None
    return DeadlineFact(
        deadline=claim.appeal_deadline,
        days_left=(claim.appeal_deadline - today).days,
        passed=today > claim.appeal_deadline,
    )


def field_definition(repo: FixtureRepo, field: str) -> str | None:
    node = repo.claim_schema["field_descriptions"].get(field)
    return str(node["description"]) if node else None


def docs_exhausted_text(repo: FixtureRepo) -> str:
    return _en(
        repo.guideline["claim_followup_settings"][
            "human_review_after_document_alternatives_exhausted"
        ]
    )


def kb_general(repo: FixtureRepo) -> dict[str, str]:
    out = {k: str(v["description"]) for k, v in repo.claim_schema["field_descriptions"].items()}
    out["default_guidance"] = _en(repo.guideline["default_guidance"])
    return out
