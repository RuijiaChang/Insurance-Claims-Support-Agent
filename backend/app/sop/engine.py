"""PolicyEngine: turn one extraction into a TurnPlan, hopping across phases.

``decide`` is the only caller of ``phases.transition`` in the application
(invariant I1): guards and phase handlers only *return* a transition, and the
LLM never changes phase. One user message may satisfy several phases at once
(e.g. full identity plus a case hint), so after a transition the new phase's
handler runs on the same extraction, up to ``sop.process.max_hops`` handler
calls per turn.

``Engine`` runs one whole turn around ``decide``: extraction (LLM reconciled with
regex, regex alone if the LLM fails), memory, policy, context, responder and
OutputGuard, falling back to deterministic templates whenever the LLM fails or its
reply cannot pass the guard.
"""

import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import Any, Literal

from app.data.repo import FixtureRepo
from app.guards.output_guard import check_reply
from app.llm.base import ExtractContext, LLMBundle, LLMError, LLMErrorKind
from app.llm.regex_extractor import extract_regex
from app.settings import SopConfig
from app.sop import phases
from app.sop.context import ResponderContext, build_context
from app.sop.extraction import Extraction, reconcile
from app.sop.memory import apply_extraction
from app.sop.phases import Phase
from app.sop.plan import Directive, FactScope, PolicyCtx, QuickReply, StepResult, TurnPlan
from app.sop.policies.global_guards import apply_global_guards
from app.sop.policies.post import handle_post
from app.sop.policies.process import handle_process
from app.sop.policies.resolve import handle_resolve
from app.sop.policies.verify import handle_verify
from app.sop.snapshot import public_snapshot
from app.sop.state import Message, SessionState, TraceEvent
from app.sop.templates import render
from app.tools.email import Outbox
from app.tools.identity import IDENTITY_FIELDS

Handler = Callable[[SessionState, Extraction, PolicyCtx], StepResult]

HANDLERS: dict[Phase, Handler] = {
    Phase.VERIFY_ID: handle_verify,
    Phase.RESOLVE_INTENT: handle_resolve,
    Phase.PROCESS_CASE: handle_process,
    Phase.POST_PROCESS: handle_post,
}
_TERMINAL = frozenset({Phase.HANDOFF, Phase.CLOSED})


def _apply(state: SessionState, step: StepResult, hops: list[Phase]) -> bool:
    """Apply the step's transition; return True if the phase changed."""
    if step.transition is None:
        return False
    before = state.phase
    phases.transition(state, *step.transition)
    if state.phase != before:
        hops.append(state.phase)
        return True
    return False


def decide(state: SessionState, ex: Extraction, ctx: PolicyCtx) -> TurnPlan:
    hops: list[Phase] = [state.phase]
    directives: list[Directive] = []
    replies: list[QuickReply] = []
    scope: FactScope = "none"

    guard = apply_global_guards(state, ex, ctx)
    if guard.stop:
        assert guard.step is not None
        step = guard.step
        directives = list(step.directives)
        replies = list(step.quick_replies)
        scope = step.fact_scope
        _apply(state, step, hops)
        if not (step.continue_hop and step.transition is not None):
            return TurnPlan(directives, replies, scope, hops)
        if state.phase in _TERMINAL:
            return TurnPlan(directives, replies, scope, hops)
    else:
        directives = list(guard.extra)

    for _ in range(ctx.sop.process.max_hops):
        if state.phase in _TERMINAL:
            break
        step = HANDLERS[state.phase](state, ex, ctx)
        directives.extend(step.directives)
        if step.quick_replies:
            replies = list(step.quick_replies)
        scope = step.fact_scope
        changed = _apply(state, step, hops)
        if not (step.continue_hop and changed):
            break

    if not replies:
        replies = list(guard.extra_replies)
    return TurnPlan(directives, replies, scope, hops)


# --- Turn orchestration -----------------------------------------------------------


@dataclass
class TurnResult:
    messages: list[Message]
    quick_replies: list[QuickReply]
    snapshot: dict[str, Any]
    llm_error: LLMErrorKind | None


def _ms(start: float) -> int:
    return int((time.perf_counter() - start) * 1000)


def _last_agent_message(state: SessionState) -> str | None:
    return next((m.text for m in reversed(state.transcript) if m.role == "agent"), None)


def _template_context(state: SessionState, directives: list[Directive]) -> ResponderContext:
    """A context for turns rendered without the pipeline (greeting, closed session)."""
    return ResponderContext(
        phase=state.phase,
        directives=directives,
        facts={},
        user_text="",
        history=[],
        tool_executor=None,
        whitelist_text="",
    )


def _extract_summary(ex: Extraction, source: str) -> str:
    # Counts and labels only: never an identity value or a field-level match result.
    fields = sum(1 for f in IDENTITY_FIELDS if getattr(ex.identity, f))
    acts = ",".join(ex.acts) or "-"
    return (
        f"{source}: identity_fields={fields} acts={acts} intent={ex.intent or '-'} "
        f"scope={ex.scope} emotion={ex.emotion.label}/{ex.emotion.intensity}"
    )


class Engine:
    def __init__(self, repo: FixtureRepo, sop: SopConfig, today: date, outbox: Outbox) -> None:
        self.repo = repo
        self.sop = sop
        self.today = today
        self.outbox = outbox

    def start(self, state: SessionState) -> TurnResult:
        """Greeting turn: ask for identity. No LLM call."""
        directive = Directive(
            kind="need_identity",
            data={
                "needed": self.sop.verification.min_matched_fields,
                "options": list(IDENTITY_FIELDS),
                "greeting": True,
            },
        )
        message = Message(
            role="agent",
            text=render([directive], _template_context(state, [directive])),
            turn=state.counters.turns,
        )
        state.transcript.append(message)
        return TurnResult([message], [], public_snapshot(state), None)

    def handle_turn(
        self,
        state: SessionState,
        llm: LLMBundle,
        *,
        text: str | None = None,
        action: str | None = None,
        event: Literal["consent_poll"] | None = None,
    ) -> TurnResult:
        state.counters.turns += 1
        turn = state.counters.turns
        if turn > self.sop.ratelimit.max_turns_per_session or state.phase in _TERMINAL:
            return self._closed_turn(state, turn)

        user_text = text or ""
        llm_error: LLMErrorKind | None = None
        if user_text:
            state.transcript.append(Message(role="user", text=user_text, turn=turn))

        # 1. Extraction: LLM reconciled with regex; regex alone if the LLM fails.
        start = time.perf_counter()
        source = "none"
        if user_text.strip():
            hits = extract_regex(user_text)
            ectx = ExtractContext(
                phase=state.phase,
                pending_question=state.pending_question,
                last_agent_message=_last_agent_message(state),
            )
            try:
                ex = reconcile(llm.extractor.extract(user_text, ectx), hits)
                source = "llm+regex"
            except LLMError as err:
                ex = Extraction.from_regex(hits)
                llm_error = err.kind
                source = "regex"
        else:
            ex = Extraction.empty()
        apply_extraction(state, ex, turn)
        self._event(state, turn, "extract", _extract_summary(ex, source), start)
        if llm_error is not None:
            self._event(state, turn, "llm_error", f"extractor: {llm_error}")

        # 2. Policy.
        start = time.perf_counter()
        ctx = PolicyCtx(
            repo=self.repo,
            sop=self.sop,
            today=self.today,
            outbox=self.outbox,
            email_composer=llm.email_composer,
            action=action,
            event=event,
            turn=turn,
            session_id=state.session_id,
            user_text=user_text,
        )
        plan = decide(state, ex, ctx)
        hops = " -> ".join(p.value for p in plan.hops)
        kinds = ", ".join(d.kind for d in plan.directives) or "-"
        self._event(state, turn, "policy", f"hops: {hops}; directives: {kinds}", start)

        # 3. Context, responder and guard (retry once with feedback, then templates).
        rctx = build_context(state, plan, ctx, user_text)
        start = time.perf_counter()
        reply, llm_error = self._respond(state, llm, rctx, llm_error, turn, start)

        message = Message(role="agent", text=reply, turn=turn)
        state.transcript.append(message)
        return TurnResult([message], list(plan.quick_replies), public_snapshot(state), llm_error)

    def _respond(
        self,
        state: SessionState,
        llm: LLMBundle,
        rctx: ResponderContext,
        llm_error: LLMErrorKind | None,
        turn: int,
        start: float,
    ) -> tuple[str, LLMErrorKind | None]:
        feedback: list[str] | None = None
        for attempt in (1, 2):
            try:
                reply = llm.responder.respond(rctx, feedback=feedback)
            except LLMError as err:
                llm_error = llm_error or err.kind
                self._event(state, turn, "llm_error", f"responder: {err.kind}")
                break
            guard = check_reply(reply, state, rctx, self.repo)
            if guard.ok:
                self._event(state, turn, "guard", f"ok (attempt {attempt})", start)
                return reply, llm_error
            # Categories only: a violation string can name the leaked record value.
            categories = sorted({v.split(":", 1)[0] for v in guard.violations})
            self._event(
                state,
                turn,
                "guard",
                f"violations: {len(guard.violations)} (attempt {attempt})",
                start,
                {"categories": categories},
            )
            feedback = guard.violations

        reply = render(rctx.directives, rctx)
        guard = check_reply(reply, state, rctx, self.repo)
        if not guard.ok:
            categories = sorted({v.split(":", 1)[0] for v in guard.violations})
            self._event(
                state,
                turn,
                "guard_template_violation",
                f"template violations: {len(guard.violations)}",
                data={"categories": categories},
            )
        else:
            self._event(state, turn, "guard", "template fallback ok", start)
        return reply, llm_error

    def _closed_turn(self, state: SessionState, turn: int) -> TurnResult:
        """Session over (terminal phase or turn cap): fixed reply, no LLM, no other change."""
        data: dict[str, Any] = {"phase": state.phase.value}
        if turn > self.sop.ratelimit.max_turns_per_session:
            data["reason"] = "max_turns"
        directive = Directive(kind="session_closed", data=data)
        text = render([directive], _template_context(state, [directive]))
        message = Message(role="agent", text=text, turn=turn)
        return TurnResult([message], [], public_snapshot(state), None)

    @staticmethod
    def _event(
        state: SessionState,
        turn: int,
        stage: str,
        summary: str,
        start: float | None = None,
        data: dict[str, Any] | None = None,
    ) -> None:
        state.events.append(
            TraceEvent(
                turn=turn,
                stage=stage,
                summary=summary,
                data=data or {},
                ms=_ms(start) if start is not None else None,
            )
        )
