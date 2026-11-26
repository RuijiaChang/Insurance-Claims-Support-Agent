"""Test helpers: policy context, extraction builder, transition applier."""

from datetime import date
from typing import Any, Literal

from app.data.repo import FixtureRepo
from app.settings import SopConfig
from app.sop import phases
from app.sop.email_summary import EmailDraft
from app.sop.extraction import Extraction
from app.sop.plan import PolicyCtx, StepResult
from app.sop.state import SessionState
from app.tools.email import Outbox


class PassThroughComposer:
    def compose(self, state: SessionState, draft: EmailDraft) -> EmailDraft:
        return draft


def make_ctx(
    repo: FixtureRepo,
    sop: SopConfig,
    *,
    today: date = date(2026, 3, 5),
    action: str | None = None,
    event: Literal["consent_poll"] | None = None,
    user_text: str = "",
    turn: int = 1,
    session_id: str = "s1",
) -> PolicyCtx:
    return PolicyCtx(
        repo=repo,
        sop=sop,
        today=today,
        outbox=Outbox(None),
        email_composer=PassThroughComposer(),
        action=action,
        event=event,
        turn=turn,
        session_id=session_id,
        user_text=user_text,
    )


def ex(**kw: Any) -> Extraction:
    return Extraction.model_validate(kw)


def apply_step(state: SessionState, step: StepResult) -> None:
    if step.transition is not None:
        phases.transition(state, *step.transition)
