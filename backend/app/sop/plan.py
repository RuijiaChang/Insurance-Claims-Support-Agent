"""Plan types produced by phase policies and consumed by the responder."""

from dataclasses import dataclass, field
from datetime import date
from typing import TYPE_CHECKING, Any, Literal, Protocol

from pydantic import BaseModel, Field

from app.data.repo import FixtureRepo
from app.settings import SopConfig
from app.sop.email_summary import EmailDraft
from app.sop.phases import Phase, SubState
from app.tools.email import Outbox

if TYPE_CHECKING:
    from app.sop.state import SessionState

DirectiveKind = Literal[
    "need_identity",
    "verify_failed",
    "locked",
    "confirm_verified",
    "acknowledge_hint",
    "explain_why",
    "offer_alternatives",
    "empathize",
    "persuade",
    "stop_persuading",
    "restate_requirement",
    "offer_handoff",
    "handoff_done",
    "rep_ask_details",
    "rep_denied",
    "consent_sent",
    "consent_waiting",
    "consent_approved",
    "consent_expired",
    "case_selected",
    "choose_case",
    "no_hints",
    "no_match",
    "no_claims",
    "answer_question",
    "deadline_passed",
    "no_data",
    "docs_exhausted",
    "anything_else",
    "offer_email",
    "email_preview",
    "email_sent",
    "email_skipped",
    "email_address_restricted",
    "closing",
    "decline_off_topic",
    "answer_general",
    "small_talk",
    "session_closed",
    "other_party_restricted",
]

FactScope = Literal["none", "claims_summary", "case", "email"]


class Directive(BaseModel):
    kind: DirectiveKind
    data: dict[str, Any] = Field(default_factory=dict)


class QuickReply(BaseModel):
    label: str
    action: str


@dataclass
class StepResult:
    directives: list[Directive]
    quick_replies: list[QuickReply]
    transition: tuple[Phase, SubState] | None = None
    continue_hop: bool = False
    fact_scope: FactScope = "none"


@dataclass
class TurnPlan:
    directives: list[Directive]
    quick_replies: list[QuickReply]
    fact_scope: FactScope
    hops: list[Phase] = field(default_factory=list)


class EmailComposer(Protocol):
    def compose(self, state: "SessionState", draft: EmailDraft) -> EmailDraft: ...


@dataclass
class PolicyCtx:
    repo: FixtureRepo
    sop: SopConfig
    today: date
    outbox: Outbox
    email_composer: EmailComposer
    action: str | None
    event: Literal["consent_poll"] | None
    turn: int
    session_id: str
    user_text: str = ""
