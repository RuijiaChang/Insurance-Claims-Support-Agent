"""Per-turn extraction schema (filled by the LLM) and regex reconciliation."""

from typing import Literal

from pydantic import BaseModel, Field

from app.llm.regex_extractor import RegexHits
from app.tools.claims import CaseHintsInput
from app.tools.guidance import GuidanceTopic, Intent
from app.tools.identity import IdentityField, Relationship

__all__ = [
    "CaseHints",
    "Emotion",
    "Extraction",
    "GuidanceTopic",
    "IdentityFields",
    "Intent",
    "RepInfo",
    "UserAct",
    "reconcile",
]

UserAct = Literal[
    "provide_info",
    "refuse_info",
    "ask_why",
    "ask_clarification",
    "request_human",
    "affirm",
    "deny",
    "select_case",
    "ask_question",
    "greeting",
    "done",
    "email_send",
    "email_skip",
    "bypass_attempt",
    "cannot_obtain",
]


class IdentityFields(BaseModel):
    full_name: str | None = None
    dob: str | None = None
    phone: str | None = None
    email: str | None = None
    id_last4: str | None = None
    policy_number: str | None = None


class RepInfo(BaseModel):
    rep_name: str | None = None
    relationship: Relationship | None = None
    policyholder_name: str | None = None


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


class CaseHints(BaseModel):
    case_id: str | None = None
    case_type: Literal["healthcare", "dental", "auto"] | None = None
    status: Literal["denied", "closed", "open"] | None = None
    month: int | None = Field(default=None, ge=1, le=12)
    year: int | None = None
    free_text: str | None = None

    def to_input(self) -> CaseHintsInput:
        return CaseHintsInput(
            case_id=_clean(self.case_id),
            case_type=(_clean(self.case_type) or "").lower() or None,
            status=(_clean(self.status) or "").lower() or None,
            month=self.month or None,
            year=self.year or None,
        )


class Emotion(BaseModel):
    label: Literal["neutral", "frustrated", "anxious", "angry", "confused", "refusing"] = "neutral"
    intensity: int = Field(default=0, ge=0, le=3)


class Extraction(BaseModel):
    identity: IdentityFields = Field(default_factory=IdentityFields)
    refused_fields: list[IdentityField] = Field(default_factory=list)
    caller_role: Literal["policyholder", "representative", "unknown"] = "unknown"
    representative: RepInfo | None = None
    case_hints: CaseHints = Field(default_factory=CaseHints)
    intent: Intent | None = None
    guidance_topic: GuidanceTopic | None = None
    question: str | None = None
    acts: list[UserAct] = Field(default_factory=list)
    scope: Literal["in_scope_claim", "in_scope_general", "small_talk", "out_of_scope"] = (
        "in_scope_claim"
    )
    emotion: Emotion = Field(default_factory=Emotion)
    email_preference: Literal["send", "skip"] | None = None

    @classmethod
    def empty(cls) -> "Extraction":
        return cls()

    @classmethod
    def from_regex(cls, h: RegexHits) -> "Extraction":
        return reconcile(None, h)


def reconcile(llm: Extraction | None, hits: RegexHits) -> Extraction:
    """Regex hits override the LLM on format fields; inputs are never mutated."""
    out = llm.model_copy(deep=True) if llm is not None else Extraction.empty()
    if hits.dob_raw:
        out.identity.dob = hits.dob_raw
    if hits.phone:
        out.identity.phone = hits.phone
    if hits.email:
        out.identity.email = hits.email
    if hits.id_last4:
        out.identity.id_last4 = hits.id_last4
    if hits.policy_number:
        out.identity.policy_number = hits.policy_number
    if hits.case_id:
        out.case_hints.case_id = hits.case_id
    return out
