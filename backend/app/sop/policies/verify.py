"""VERIFY_ID policy: strict 3-of-5 identity gate, representative check and consent.

Security rules enforced here:
- no record data is emitted before verification (only field names and counts);
- a failed attempt never says which field matched or mismatched, nor whether an
  account exists;
- a representative never gets access before the policyholder approves consent.

Handlers never change phase themselves: they return ``StepResult.transition``.
"""

import calendar
import json

from app.sop.extraction import Extraction
from app.sop.phases import Phase, SubState
from app.sop.plan import Directive, PolicyCtx, QuickReply, StepResult
from app.sop.policies.handoff import start_handoff
from app.sop.state import PendingQuestion, SessionState
from app.tools.consent import poll_consent, request_consent, resend_consent
from app.tools.email import mask_phone
from app.tools.identity import match_representative, verify

HANDOFF_REPLY = QuickReply(label="Talk to a representative", action="handoff_accept")
END_REPLY = QuickReply(label="End conversation", action="end_session")
RESEND_REPLY = QuickReply(label="Resend consent request", action="consent_resend")

_HINT_SLOTS = ("case_quote", "case_type", "status", "month", "year")


def handle_verify(state: SessionState, ex: Extraction, ctx: PolicyCtx) -> StepResult:
    sub = state.sub_state
    if sub == SubState.COLLECTING:
        return _collecting(state, ex, ctx)
    if sub == SubState.REP_CHECK:
        return _rep_check(state, ctx)
    if sub == SubState.CONSENT_PENDING:
        return _consent_pending(state, ctx)
    if sub == SubState.CONSENT_EXPIRED:
        return _consent_expired_input(state, ctx)
    if sub == SubState.REP_DENIED:
        return _close(state) if ctx.action == "end_session" else _rep_denied(state, None)
    if sub == SubState.LOCKED:
        return _lock(state, ctx)
    raise ValueError(f"unexpected VERIFY_ID sub-state: {sub}")


# --- COLLECTING ---------------------------------------------------------------


def _comparison_fingerprint(state: SessionState) -> str:
    """Canonical form of exactly what a comparison would use.

    Restating a stored value, or refusing a field that was never given, leaves it
    unchanged, so the same submission is never counted as a second failure.
    """
    identity = state.identity
    refused = identity.refused()
    usable = {f: sorted(v) for f, v in identity.values().items() if f not in refused}
    return json.dumps({"values": usable, "policy_number": identity.policy_number}, sort_keys=True)


def _collecting(state: SessionState, ex: Extraction, ctx: PolicyCtx) -> StepResult:
    cfg = ctx.sop.verification
    identity = state.identity
    provided = identity.provided_count()
    options: list[str] = list(identity.remaining_options())
    pre = _preamble(state, ex, ctx)

    if provided < cfg.min_matched_fields:
        main = Directive(
            kind="need_identity",
            data={"needed": cfg.min_matched_fields - provided, "options": options},
        )
    elif (fingerprint := _comparison_fingerprint(state)) != state.last_failed_fingerprint:
        outcome = verify(
            identity.values(),
            identity.refused(),
            identity.policy_number,
            ctx.repo.policyholders,
            cfg.name_fuzzy_threshold,
            cfg.min_matched_fields,
        )
        if outcome.status == "pass" and outcome.party_id is not None:
            state.verified_party_id = outcome.party_id
            state.identity.matched_fields = sorted(outcome.matched_fields)
            state.pending_question = None
            step = _on_verified(state, ctx)
            step.directives = pre + step.directives
            return step
        state.verification_failures += 1
        state.last_failed_fingerprint = fingerprint
        if state.verification_failures >= cfg.max_failures:
            return _lock(state, ctx)
        # Deliberately only the option list: no field-level result, no account hint.
        main = Directive(kind="verify_failed", data={"options": options})
    else:
        # Same data as the last failed comparison: repeat without counting a failure.
        main = Directive(kind="verify_failed", data={"options": options, "repeat": True})

    state.pending_question = PendingQuestion(kind="need_identity")
    directives = [*pre, main]
    quick_replies: list[QuickReply] = []
    if "refuse_info" in ex.acts or ex.refused_fields:
        directives.append(Directive(kind="offer_alternatives", data={"options": options}))
        if provided + len(options) < cfg.min_matched_fields:
            directives.append(Directive(kind="offer_handoff", data={"reason": "verify"}))
            quick_replies.append(HANDOFF_REPLY)
            state.pending_question = PendingQuestion(kind="offer_handoff")
    return StepResult(directives=directives, quick_replies=quick_replies)


def _preamble(state: SessionState, ex: Extraction, ctx: PolicyCtx) -> list[Directive]:
    out: list[Directive] = []
    slots = state.memory.slots
    if any(k in slots and slots[k].captured_turn == ctx.turn for k in _HINT_SLOTS):
        out.append(Directive(kind="acknowledge_hint", data={"quote": _hint_quote(state)}))
    if "ask_why" in ex.acts:
        out.append(Directive(kind="explain_why", data={"gate": "verify"}))
    return out


def _hint_quote(state: SessionState) -> str:
    """The user's own words if we have them, else a phrase built from their hints."""
    mem = state.memory
    quote = mem.get("case_quote")
    if quote:
        return quote
    words = ["your", mem.get("status"), mem.get("case_type"), "claim"]
    phrase = " ".join(w for w in words if w)
    month, year = mem.get("month"), mem.get("year")
    when = [calendar.month_name[int(month)] if month and month.isdigit() else None, year]
    if any(when):
        phrase += " from " + " ".join(w for w in when if w)
    return phrase


def _lock(state: SessionState, ctx: PolicyCtx) -> StepResult:
    state.pending_question = None
    handoff = start_handoff(state, "locked", ctx)
    handoff.directives = [Directive(kind="locked"), *handoff.directives]
    return handoff


# --- Verified: policyholder or representative -----------------------------------


def _on_verified(state: SessionState, ctx: PolicyCtx) -> StepResult:
    if state.caller.role != "representative":
        state.access_granted = True
        return StepResult(
            directives=[Directive(kind="confirm_verified")],
            quick_replies=[],
            transition=(Phase.RESOLVE_INTENT, SubState.NONE),
            continue_hop=True,
        )
    return _rep_check(state, ctx)


def _rep_check(state: SessionState, ctx: PolicyCtx) -> StepResult:
    party_id = state.verified_party_id
    if party_id is None:  # pragma: no cover - REP_CHECK is only entered after a pass
        raise ValueError("REP_CHECK without a verified party")
    caller = state.caller
    if not caller.rep_name or caller.relationship is None:
        missing = [
            name
            for name, value in (
                ("rep_name", caller.rep_name),
                ("relationship", caller.relationship),
            )
            if not value
        ]
        return StepResult(
            directives=[Directive(kind="rep_ask_details", data={"missing": missing})],
            quick_replies=[],
            transition=(Phase.VERIFY_ID, SubState.REP_CHECK),
        )
    registered = match_representative(
        caller.rep_name,
        caller.relationship,
        party_id,
        ctx.repo.representatives,
        ctx.sop.verification.name_fuzzy_threshold,
    )
    if not registered:
        return _rep_denied(state, (Phase.VERIFY_ID, SubState.REP_DENIED))
    state.consent = request_consent(state.consent)
    return _consent_sent(state, ctx)


def _rep_denied(state: SessionState, transition: tuple[Phase, SubState] | None) -> StepResult:
    state.pending_question = PendingQuestion(kind="rep_denied")
    return StepResult(
        directives=[Directive(kind="rep_denied")],
        quick_replies=[HANDOFF_REPLY, END_REPLY],
        transition=transition,
    )


# --- Consent ------------------------------------------------------------------


def _consent_sent(state: SessionState, ctx: PolicyCtx) -> StepResult:
    if state.verified_party_id is None:  # pragma: no cover - consent follows a pass
        raise ValueError("consent requested without a verified party")
    holder = ctx.repo.holder(state.verified_party_id)
    state.pending_question = None
    return StepResult(
        directives=[
            Directive(kind="consent_sent", data={"masked_phone": mask_phone(holder.phone)})
        ],
        quick_replies=[],
        transition=(Phase.VERIFY_ID, SubState.CONSENT_PENDING),
    )


def _consent_pending(state: SessionState, ctx: PolicyCtx) -> StepResult:
    # Both a consent_poll system event and any user message advance the poll once.
    state.consent = poll_consent(state.consent, ctx.repo.consent_scenarios)
    if state.consent.status == "approved":
        state.access_granted = True
        state.pending_question = None
        return StepResult(
            directives=[Directive(kind="consent_approved")],
            quick_replies=[],
            transition=(Phase.RESOLVE_INTENT, SubState.NONE),
            continue_hop=False,
        )
    if state.consent.status == "expired":
        return _consent_expired(state, ctx, (Phase.VERIFY_ID, SubState.CONSENT_EXPIRED))
    return StepResult(directives=[Directive(kind="consent_waiting")], quick_replies=[])


def _consent_expired(
    state: SessionState, ctx: PolicyCtx, transition: tuple[Phase, SubState] | None
) -> StepResult:
    can_resend = state.consent.resends < ctx.sop.consent.max_resends
    quick_replies = [RESEND_REPLY] if can_resend else []
    quick_replies += [HANDOFF_REPLY, END_REPLY]
    state.pending_question = PendingQuestion(kind="consent_expired")
    return StepResult(
        directives=[Directive(kind="consent_expired", data={"can_resend": can_resend})],
        quick_replies=quick_replies,
        transition=transition,
    )


def _consent_expired_input(state: SessionState, ctx: PolicyCtx) -> StepResult:
    if ctx.action == "end_session":
        return _close(state)
    if ctx.action == "consent_resend":
        resent = resend_consent(state.consent, ctx.sop.consent.max_resends)
        if resent is not None:
            state.consent = request_consent(resent)
            return _consent_sent(state, ctx)
    return _consent_expired(state, ctx, None)


def _close(state: SessionState) -> StepResult:
    state.pending_question = None
    return StepResult(
        directives=[Directive(kind="closing")],
        quick_replies=[],
        transition=(Phase.CLOSED, SubState.NONE),
    )
