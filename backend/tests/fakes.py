"""Test helpers: policy context, extraction builder, transition applier, fake LLMs, engine."""

from datetime import date
from typing import Any, Literal

from app.data.repo import FixtureRepo
from app.llm.base import ExtractContext, LLMBundle, LLMError, LLMErrorKind, Responder
from app.settings import SopConfig
from app.sop import phases
from app.sop.context import ResponderContext
from app.sop.email_summary import EmailDraft
from app.sop.engine import Engine
from app.sop.extraction import Extraction
from app.sop.plan import PolicyCtx, StepResult
from app.sop.state import SessionState
from app.sop.templates import render
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


class FakeExtractor:
    """Returns the scripted extraction for the exact text, else an empty one."""

    def __init__(
        self, script: dict[str, Extraction], raise_kind: LLMErrorKind | None = None
    ) -> None:
        self.script = script
        self.raise_kind = raise_kind
        self.calls: list[ExtractContext] = []

    def extract(self, text: str, ectx: ExtractContext) -> Extraction:
        self.calls.append(ectx)
        if self.raise_kind is not None:
            raise LLMError(self.raise_kind, "fake extractor failure")
        hit = self.script.get(text)
        return hit.model_copy(deep=True) if hit is not None else Extraction.empty()


class TemplateResponder:
    """Deterministic responder: renders the directive templates; records every context."""

    def __init__(self) -> None:
        self.contexts: list[ResponderContext] = []

    def respond(self, rctx: ResponderContext, feedback: list[str] | None = None) -> str:
        self.contexts.append(rctx)
        return render(rctx.directives, rctx)


class ScriptedResponder:
    """Returns scripted replies in order; an ``LLMError`` entry is raised instead.

    Records every context and the feedback passed with each call.
    """

    def __init__(self, replies: list[str | LLMError]) -> None:
        self.replies = list(replies)
        self.contexts: list[ResponderContext] = []
        self.feedback: list[list[str] | None] = []

    def respond(self, rctx: ResponderContext, feedback: list[str] | None = None) -> str:
        self.contexts.append(rctx)
        self.feedback.append(feedback)
        reply = self.replies.pop(0)
        if isinstance(reply, LLMError):
            raise reply
        return reply


class FakeEmailComposer(PassThroughComposer):
    """Returns the deterministic draft unchanged."""


def make_bundle(
    script: dict[str, Extraction],
    raise_kind: LLMErrorKind | None = None,
    responder: Responder | None = None,
) -> LLMBundle:
    return LLMBundle(
        extractor=FakeExtractor(script, raise_kind),
        responder=responder if responder is not None else TemplateResponder(),
        email_composer=FakeEmailComposer(),
    )


def make_engine(repo: FixtureRepo, sop: SopConfig, *, today: date = date(2026, 3, 5)) -> Engine:
    return Engine(repo, sop, today, Outbox(None))
