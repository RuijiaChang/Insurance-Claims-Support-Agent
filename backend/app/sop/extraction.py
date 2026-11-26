"""Per-turn extraction schema (filled by the LLM) and regex reconciliation."""

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.config import JsonDict

from app.llm.regex_extractor import RegexHits, date_candidates, phone_candidates
from app.tools.claims import CaseHintsInput
from app.tools.guidance import GuidanceTopic, Intent
from app.tools.identity import (
    IdentityField,
    Relationship,
    normalize_name,
    normalize_phone,
    parse_dob,
)

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


def _drop_property_defaults(schema: JsonDict) -> None:
    """OpenAI strict structured outputs reject ``default``; the Python defaults still apply."""
    properties = schema.get("properties")
    if isinstance(properties, dict):
        for prop in properties.values():
            if isinstance(prop, dict):
                prop.pop("default", None)


_STRICT_SCHEMA = ConfigDict(json_schema_extra=_drop_property_defaults)


class IdentityFields(BaseModel):
    model_config = _STRICT_SCHEMA

    full_name: str | None = None
    dob: str | None = None
    phone: str | None = None
    email: str | None = None
    id_last4: str | None = None
    policy_number: str | None = None


class RepInfo(BaseModel):
    model_config = _STRICT_SCHEMA

    rep_name: str | None = None
    relationship: Relationship | None = None
    policyholder_name: str | None = None


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


class CaseHints(BaseModel):
    model_config = _STRICT_SCHEMA

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
    model_config = _STRICT_SCHEMA

    label: Literal["neutral", "frustrated", "anxious", "angry", "confused", "refusing"] = "neutral"
    intensity: int = Field(default=0, ge=0, le=3)


class Extraction(BaseModel):
    model_config = _STRICT_SCHEMA

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
        return reconcile(None, h, "")


def _has_token(text: str, value: str) -> bool:
    return re.search(rf"(?<!\w){re.escape(value)}(?!\w)", text, re.IGNORECASE) is not None


def _grounded(field: str, value: str, text: str) -> bool:
    """Did the caller actually say this identity value in this message?"""
    value = value.strip()
    if not value:
        return False
    if field in ("id_last4", "policy_number"):
        return _has_token(text, value)
    if field == "email":
        return value.casefold() in text.casefold()
    if field == "phone":
        phone = normalize_phone(value)
        return phone is not None and any(
            normalize_phone(c) == phone for c in phone_candidates(text)
        )
    if field == "dob":
        wanted = set(parse_dob(value))
        return bool(wanted) and any(wanted & set(parse_dob(c)) for c in date_candidates(text))
    if field == "full_name":
        said = set(normalize_name(text).split())
        tokens = normalize_name(value).split()
        return bool(tokens) and all(t in said for t in tokens)
    return False


_GROUNDED_IDENTITY = ("full_name", "dob", "phone", "email", "id_last4", "policy_number")

# Words a caller might use for each case hint; used only to check a hint is grounded.
_HINT_WORDS = {
    "healthcare": ("health", "medical", "hospital", "doctor", "clinic", "surgery", "biopsy"),
    "dental": ("dental", "dentist", "tooth", "teeth", "crown", "orthodont"),
    "auto": ("auto", "car", "vehicle", "accident", "collision", "crash"),
    "denied": ("deni", "deny", "reject", "declin", "turned down"),
    "closed": ("closed", "paid", "settled", "finished", "done"),
    "open": ("open", "pending", "progress", "review", "ongoing"),
}
_MONTHS = (
    "jan",
    "feb",
    "mar",
    "apr",
    "may",
    "jun",
    "jul",
    "aug",
    "sep",
    "oct",
    "nov",
    "dec",
)


def _case_hints_grounded(h: CaseHints, text: str) -> bool:
    """Does the caller's own message mention anything these case hints claim?"""
    low = text.casefold()
    if h.free_text and h.free_text.strip().casefold() in low:
        return True
    if h.case_id and _has_token(text, h.case_id):
        return True
    for value in (h.case_type, h.status):
        if value and (value in low or any(w in low for w in _HINT_WORDS.get(value, ()))):
            return True
    if h.month and (_MONTHS[h.month - 1] in low or _has_token(text, str(h.month))):
        return True
    return bool(h.year and _has_token(text, str(h.year)))


def reconcile(llm: Extraction | None, hits: RegexHits, user_text: str) -> Extraction:
    """Merge LLM extraction with regex hits; inputs are never mutated.

    An LLM identity value the caller did not actually say in ``user_text`` is dropped,
    so a model can never fill in (and so verify with) a detail the caller didn't give.
    Regex hits come from the text itself and override the LLM on format fields.
    """
    out = llm.model_copy(deep=True) if llm is not None else Extraction.empty()
    for field in _GROUNDED_IDENTITY:
        value = getattr(out.identity, field)
        if value is not None and not _grounded(field, value, user_text):
            setattr(out.identity, field, None)
    # Case hints get the same rule, except when the caller picks from options the agent
    # listed ("the second one"): then the hints legitimately come from the agent's message.
    if "select_case" not in out.acts:
        hints = out.case_hints
        if hints.free_text and hints.free_text.strip().casefold() not in user_text.casefold():
            hints.free_text = None
        if not _case_hints_grounded(hints, user_text):
            out.case_hints = CaseHints()
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
