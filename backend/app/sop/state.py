"""Session state models."""

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.sop.email_summary import EmailDraft
from app.sop.phases import Phase, SubState
from app.tools.consent import ConsentState
from app.tools.guidance import Intent
from app.tools.handoff import HandoffReason, HandoffTicket
from app.tools.identity import IDENTITY_FIELDS, IdentityField, Relationship


class IdentityEntry(BaseModel):
    values: list[str] = Field(default_factory=list)
    status: Literal["pending", "provided", "refused"] = "pending"
    captured_turn: int = 0


def _initial_fields() -> dict[IdentityField, IdentityEntry]:
    return {f: IdentityEntry() for f in IDENTITY_FIELDS}


class IdentityClaims(BaseModel):
    fields: dict[IdentityField, IdentityEntry] = Field(default_factory=_initial_fields)
    policy_number: str | None = None
    matched_fields: list[IdentityField] = Field(default_factory=list)

    def add(self, field: IdentityField, raw: str, turn: int) -> None:
        raw = raw.strip()
        if not raw:
            return
        entry = self.fields[field]
        if raw not in entry.values:
            entry.values.append(raw)
        entry.status = "provided"
        entry.captured_turn = turn

    def refuse(self, field: IdentityField, turn: int) -> None:
        entry = self.fields[field]
        entry.status = "refused"
        entry.captured_turn = turn

    def values(self) -> dict[IdentityField, list[str]]:
        return {f: list(e.values) for f, e in self.fields.items() if e.values}

    def refused(self) -> set[IdentityField]:
        return {f for f, e in self.fields.items() if e.status == "refused"}

    def provided_count(self) -> int:
        return sum(1 for e in self.fields.values() if e.status == "provided" and e.values)

    def remaining_options(self) -> list[IdentityField]:
        return [f for f in IDENTITY_FIELDS if self.fields[f].status == "pending"]


class CallerInfo(BaseModel):
    role: Literal["policyholder", "representative", "unknown"] = "unknown"
    rep_name: str | None = None
    relationship: Relationship | None = None
    policyholder_name: str | None = None


class HintRecord(BaseModel):
    value: str
    captured_turn: int
    captured_phase: Phase
    used_phase: Phase | None = None


MEMORY_KEYS: frozenset[str] = frozenset(
    {"case_id", "case_type", "status", "month", "year", "intent", "email_preference", "case_quote"}
)


class Memory(BaseModel):
    slots: dict[str, HintRecord] = Field(default_factory=dict)
    history: list[tuple[str, HintRecord]] = Field(default_factory=list)

    def get(self, key: str) -> str | None:
        rec = self.slots.get(key)
        return rec.value if rec else None

    def set(self, key: str, value: str, turn: int, phase: Phase) -> None:
        if key not in MEMORY_KEYS:
            raise ValueError(f"unknown memory slot: {key}")
        old = self.slots.get(key)
        if old is not None:
            if old.value == value:
                return
            self.history.append((key, old))
        self.slots[key] = HintRecord(value=value, captured_turn=turn, captured_phase=phase)

    def mark_used(self, key: str, phase: Phase) -> None:
        rec = self.slots.get(key)
        if rec is not None:
            rec.used_phase = phase


Gate = Literal["verify", "consent", "email_address"]


class Counters(BaseModel):
    off_topic_total: int = 0
    off_topic_consecutive: int = 0
    persuasion_attempts: dict[Gate, int] = Field(default_factory=dict)
    l3_offered: dict[Gate, bool] = Field(default_factory=dict)
    l3_declined: dict[Gate, bool] = Field(default_factory=dict)
    negative_emotion_streak: int = 0
    turns: int = 0


class PendingQuestion(BaseModel):
    kind: Literal[
        "need_identity",
        "choose_case",
        "anything_else",
        "offer_email",
        "confirm_send",
        "offer_handoff",
        "consent_expired",
        "rep_denied",
    ]
    options: list[str] = Field(default_factory=list)


class EmailState(BaseModel):
    decision: Literal["send", "skip"] | None = None
    preview: EmailDraft | None = None
    sent_message_id: str | None = None


class CaseLogEntry(BaseModel):
    case_id: str
    kind: Literal["fact", "next_step", "deadline"]
    text: str


class Message(BaseModel):
    role: Literal["user", "agent", "system"]
    text: str
    turn: int


class TraceEvent(BaseModel):
    turn: int
    stage: str
    summary: str
    data: dict[str, Any] = Field(default_factory=dict)
    ms: int | None = None


class SessionState(BaseModel):
    session_id: str
    phase: Phase = Phase.VERIFY_ID
    sub_state: SubState = SubState.COLLECTING
    caller: CallerInfo = Field(default_factory=CallerInfo)
    identity: IdentityClaims = Field(default_factory=IdentityClaims)
    verified_party_id: str | None = None
    access_granted: bool = False
    verification_failures: int = 0
    consent: ConsentState = Field(default_factory=ConsentState)
    memory: Memory = Field(default_factory=Memory)
    active_case_id: str | None = None
    discussed_case_ids: list[str] = Field(default_factory=list)
    primary_intent: Intent | None = None
    turn_intent: Intent | None = None
    pending_handoff: HandoffReason | None = None
    case_log: list[CaseLogEntry] = Field(default_factory=list)
    counters: Counters = Field(default_factory=Counters)
    pending_question: PendingQuestion | None = None
    email: EmailState = Field(default_factory=EmailState)
    handoff: HandoffTicket | None = None
    transcript: list[Message] = Field(default_factory=list)
    events: list[TraceEvent] = Field(default_factory=list)
    alternatives_offered: list[str] = Field(default_factory=list)
    last_emotion: tuple[str, int] | None = None

    @classmethod
    def new(cls, session_id: str, consent_scenario: str = "default") -> "SessionState":
        return cls(
            session_id=session_id,
            phase=Phase.VERIFY_ID,
            sub_state=SubState.COLLECTING,
            consent=ConsentState(scenario=consent_scenario),
        )
