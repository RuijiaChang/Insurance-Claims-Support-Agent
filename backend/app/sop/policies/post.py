"""POST_PROCESS policy: offer an email summary, preview it, send or skip, then finish.

Handlers never change phase themselves: they return ``StepResult.transition``.
Mail only ever goes to the policyholder's registered address.
"""

import re

from app.sop.email_summary import build_email_draft
from app.sop.extraction import Extraction
from app.sop.phases import Phase, SubState
from app.sop.plan import Directive, PolicyCtx, QuickReply, StepResult
from app.sop.policies.handoff import start_handoff
from app.sop.state import PendingQuestion, SessionState
from app.tools.email import mask_email

_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_OFFER_REPLIES = [("Send summary", "email_send"), ("No thanks", "email_skip")]
_PREVIEW_REPLIES = [("Send", "email_confirm"), ("Skip", "email_skip")]


def _replies(pairs: list[tuple[str, str]]) -> list[QuickReply]:
    return [QuickReply(label=label, action=action) for label, action in pairs]


def handle_post(state: SessionState, ex: Extraction, ctx: PolicyCtx) -> StepResult:
    if state.verified_party_id is None:
        raise RuntimeError("POST_PROCESS reached without a verified policyholder")
    holder = ctx.repo.holder(state.verified_party_id)
    to_masked = mask_email(holder.email)
    pending = state.pending_question.kind if state.pending_question else None
    acts = ex.acts
    action = ctx.action

    if pending not in ("offer_email", "confirm_send") and state.email.decision is None:
        return _offer(state, to_masked)

    if "ask_question" in acts and state.active_case_id:
        state.pending_question = None
        return StepResult(
            directives=[],
            quick_replies=[],
            transition=(Phase.PROCESS_CASE, SubState.ACTIVE),
            continue_hop=True,
        )

    in_preview = pending == "confirm_send"
    if _other_address(ctx.user_text, holder.email):
        return StepResult(
            directives=[Directive(kind="email_address_restricted", data={"to_masked": to_masked})],
            quick_replies=_replies(_PREVIEW_REPLIES if in_preview else _OFFER_REPLIES),
            fact_scope="email" if in_preview else "none",
        )

    # Ending the conversation at the offer or the preview is a skip, then the finish.
    skip = (
        action in ("email_skip", "end_session")
        or "email_skip" in acts
        or ("deny" in acts and pending in ("offer_email", "confirm_send"))
    )
    if skip:
        state.email.decision = "skip"
        return _finish(state, ctx, [Directive(kind="email_skipped")])

    if in_preview and (action == "email_confirm" or "affirm" in acts or "email_send" in acts):
        if state.email.preview is None:
            raise RuntimeError("Email confirmation without a preview")
        message_id = ctx.outbox.send(ctx.session_id, holder.email, state.email.preview)
        state.email.decision = "send"
        state.email.sent_message_id = message_id
        return _finish(
            state,
            ctx,
            [Directive(kind="email_sent", data={"message_id": message_id, "to_masked": to_masked})],
        )

    if not in_preview and (
        action == "email_send"
        or "email_send" in acts
        or (pending == "offer_email" and "affirm" in acts)
    ):
        draft = ctx.email_composer.compose(state, build_email_draft(state, ctx.repo))
        state.email.preview = draft
        return _preview(state, draft.model_dump(), transition=True)

    if in_preview and state.email.preview is not None:
        return _preview(state, state.email.preview.model_dump(), transition=False)
    return _offer(state, to_masked)


def _offer(state: SessionState, to_masked: str) -> StepResult:
    state.pending_question = PendingQuestion(kind="offer_email")
    return StepResult(
        directives=[
            Directive(
                kind="offer_email",
                data={"to_masked": to_masked, "preference": state.memory.get("email_preference")},
            )
        ],
        quick_replies=_replies(_OFFER_REPLIES),
        transition=(Phase.POST_PROCESS, SubState.OFFER),
    )


def _preview(state: SessionState, draft: dict[str, object], *, transition: bool) -> StepResult:
    state.pending_question = PendingQuestion(kind="confirm_send")
    return StepResult(
        directives=[Directive(kind="email_preview", data={"draft": draft})],
        quick_replies=_replies(_PREVIEW_REPLIES),
        transition=(Phase.POST_PROCESS, SubState.PREVIEW) if transition else None,
        fact_scope="email",
    )


def _finish(state: SessionState, ctx: PolicyCtx, directives: list[Directive]) -> StepResult:
    state.pending_question = None
    if state.pending_handoff is not None:
        handoff = start_handoff(state, state.pending_handoff, ctx)
        return StepResult(
            directives=[*directives, *handoff.directives],
            quick_replies=[],
            transition=handoff.transition,
        )
    return StepResult(
        directives=[*directives, Directive(kind="closing")],
        quick_replies=[],
        transition=(Phase.CLOSED, SubState.NONE),
    )


def _other_address(text: str, registered: str) -> bool:
    return any(m.lower() != registered.lower() for m in _EMAIL_RE.findall(text))
