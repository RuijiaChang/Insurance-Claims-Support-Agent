"""Deterministic English templates: the no-LLM fallback and the test responder.

``render`` turns a plan's directives into one reply, one sentence or short paragraph
per directive, in order. Templates use only the directive's data and the responder
context's facts (which already obey the access rules), never invented values, so a
rendered reply always passes the OutputGuard.
"""

from collections.abc import Callable
from typing import Any

from app.sop.context import ResponderContext
from app.sop.email_summary import EmailDraft
from app.sop.phases import Phase
from app.sop.plan import Directive, DirectiveKind
from app.tools.guidance import documents_phrase

FIELD_LABELS: dict[str, str] = {
    "full_name": "full name",
    "dob": "date of birth",
    "phone": "phone number",
    "email": "email address",
    "id_last4": "last four digits of SSN or national ID",
}
_REP_LABELS = {"rep_name": "your name", "relationship": "your relationship to the policyholder"}
_ALL_FIELDS = (
    "full name, date of birth, phone number, email address, "
    "or the last four digits of your SSN or national ID"
)
_HANDOFF_OFFER = "If you'd like, I can connect you with a representative instead."

Template = Callable[[dict[str, Any], ResponderContext, list[Directive]], str]


def _join_or(items: list[str]) -> str:
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    if len(items) == 2:
        return f"{items[0]} or {items[1]}"
    return ", ".join(items[:-1]) + f", or {items[-1]}"


def _fields(options: Any) -> list[str]:
    return [FIELD_LABELS.get(str(o), str(o).replace("_", " ")) for o in options or []]


def _numbered(options: Any) -> str:
    return "; ".join(f"{i}) {o}" for i, o in enumerate(options or [], start=1))


def _has(directives: list[Directive], kind: DirectiveKind) -> bool:
    return any(d.kind == kind for d in directives)


# --- VERIFY_ID ----------------------------------------------------------------


def _need_identity(data: dict[str, Any], rctx: ResponderContext, ds: list[Directive]) -> str:
    if data.get("greeting"):
        return (
            "Hi, I'm the claims support assistant. Before I can look at any claim, I need to "
            f"verify your identity: please share any three of your {_ALL_FIELDS}."
        )
    needed = int(data.get("needed") or 0)
    if needed <= 0:
        return "Thank you — I have enough details to check your identity."
    options = _fields(data.get("options"))
    if not options:
        return f"To protect your information I need {needed} more identity detail(s)."
    return f"To protect your information I need {needed} more of: {_join_or(options)}."


def _verify_failed(data: dict[str, Any], rctx: ResponderContext, ds: list[Directive]) -> str:
    text = (
        "I wasn't able to verify with that information — please double-check or add another detail."
    )
    options = _fields(data.get("options"))
    if options:
        text += f" You can also use your {_join_or(options)}."
    return text


def _acknowledge_hint(data: dict[str, Any], rctx: ResponderContext, ds: list[Directive]) -> str:
    quote = str(data.get("quote") or "").strip()
    if not quote:
        noted = "I've noted the claim details you mentioned"
    elif quote.lower().startswith("your "):
        noted = f"I've noted you're calling about {quote}"
    else:
        noted = f'I\'ve noted what you told me about your claim: "{quote}"'
    if _has(ds, "confirm_verified"):
        return noted + "."
    return noted + " — I'll pull it up as soon as you're verified."


_WHY: dict[str, str] = {
    "verify": (
        "I ask for these details because claim records contain your health and claim "
        "information, and verifying first protects them from anyone who isn't you."
    ),
    "consent": (
        "I need the policyholder's approval because only people the policyholder approves "
        "can see their claim."
    ),
    "email_address": (
        "For your security the summary can only go to the email address on file, so it can "
        "never be redirected to someone else."
    ),
}


def _explain_why(data: dict[str, Any], rctx: ResponderContext, ds: list[Directive]) -> str:
    return _WHY.get(str(data.get("gate")), _WHY["verify"])


def _offer_alternatives(data: dict[str, Any], rctx: ResponderContext, ds: list[Directive]) -> str:
    options = _fields(data.get("options"))
    if not options:
        return "If you'd rather not share that, I can connect you with a representative."
    return f"If you'd rather not share that, you can use your {_join_or(options)} instead."


_EMPATHY: dict[str, str] = {
    "angry": (
        "I hear you, and I'm sorry this has been so frustrating — "
        "you shouldn't have to repeat yourself."
    ),
    "frustrated": "I understand this is frustrating, and I'll keep this as quick as I can.",
    "anxious": (
        "I understand this is worrying — I'll walk you through each step "
        "so you know exactly what happens next."
    ),
    "confused": "No problem — let's take this one simple step at a time.",
    "refusing": "I understand you'd prefer not to share that, and that's your choice.",
}


def _empathize(data: dict[str, Any], rctx: ResponderContext, ds: list[Directive]) -> str:
    return _EMPATHY.get(str(data.get("label")), "I understand, and I'm here to help.")


_PERSUADE: dict[str, str] = {
    "verify": (
        "Your claim details are protected: verifying first protects your health and claim "
        "information, and it's the only way I can open your claim. "
        "As soon as you're verified I'll go straight to your question."
    ),
    "consent": (
        "This step exists because only people the policyholder approves can see the claim. "
        "As soon as the policyholder approves the request, I can help you with it."
    ),
    "email_address": (
        "The summary can only go to the email address on file so it can't be redirected. "
        "You can still have it sent there, or skip the email."
    ),
}


def _persuade(data: dict[str, Any], rctx: ResponderContext, ds: list[Directive]) -> str:
    return _PERSUADE.get(str(data.get("gate")), _PERSUADE["verify"])


def _stop_persuading(data: dict[str, Any], rctx: ResponderContext, ds: list[Directive]) -> str:
    return "I don't want to keep pushing you on this."


_RESTATE: dict[str, str] = {
    "verify": "I still need verified identity details before I can discuss any claim.",
    "consent": "I still need the policyholder's approval before I can share claim details.",
    "email_address": "The summary can only be sent to the email address on file.",
}


def _restate(data: dict[str, Any], rctx: ResponderContext, ds: list[Directive]) -> str:
    return _RESTATE.get(str(data.get("gate")), _RESTATE["verify"])


def _offer_handoff(data: dict[str, Any], rctx: ResponderContext, ds: list[Directive]) -> str:
    if data.get("reason") == "verify":
        return (
            "If you can't provide enough details, I can connect you with a representative "
            "who can help."
        )
    return "Would you like me to connect you with a representative who can help further?"


def _locked(data: dict[str, Any], rctx: ResponderContext, ds: list[Directive]) -> str:
    return (
        "For your security I can't continue verification in this chat "
        "after several unsuccessful attempts."
    )


def _handoff_done(data: dict[str, Any], rctx: ResponderContext, ds: list[Directive]) -> str:
    ticket = data.get("ticket_id")
    ref = f" (ticket {ticket})" if ticket else ""
    return f"I've passed this conversation to a representative{ref}; they'll follow up with you."


def _rep_ask_details(data: dict[str, Any], rctx: ResponderContext, ds: list[Directive]) -> str:
    missing = [_REP_LABELS.get(str(m), str(m)) for m in data.get("missing") or []]
    wanted = " and ".join(missing) if missing else "your name and relationship to them"
    return f"Since you're calling on the policyholder's behalf, please tell me {wanted}."


def _rep_denied(data: dict[str, Any], rctx: ResponderContext, ds: list[Directive]) -> str:
    return (
        "I'm not able to share this policyholder's claim information with you, because you're "
        "not listed as an approved representative. I can connect you with a representative, "
        "or we can end the conversation."
    )


def _consent_sent(data: dict[str, Any], rctx: ResponderContext, ds: list[Directive]) -> str:
    phone = data.get("masked_phone")
    where = f"the policyholder's phone on file ({phone})" if phone else "the policyholder's phone"
    return (
        f"I've sent a consent request to {where}. "
        "Once they approve it, I can help you with the claim."
    )


def _consent_waiting(data: dict[str, Any], rctx: ResponderContext, ds: list[Directive]) -> str:
    return "I'm still waiting for the policyholder to approve the consent request."


def _consent_approved(data: dict[str, Any], rctx: ResponderContext, ds: list[Directive]) -> str:
    return "The policyholder has approved — I can now help you with their claims."


def _consent_expired(data: dict[str, Any], rctx: ResponderContext, ds: list[Directive]) -> str:
    text = "The consent request expired before the policyholder approved it."
    if data.get("can_resend"):
        return (
            text + " I can resend it once, connect you with a representative, or we can end here."
        )
    return text + " I can connect you with a representative, or we can end here."


def _confirm_verified(data: dict[str, Any], rctx: ResponderContext, ds: list[Directive]) -> str:
    return "Thank you — you're verified."


# --- RESOLVE_INTENT -------------------------------------------------------------


def _case_selected(data: dict[str, Any], rctx: ResponderContext, ds: list[Directive]) -> str:
    line = data.get("summary_line")
    text = f"I've pulled up your {line}." if line else "I've pulled up your claim."
    if data.get("other_case_hint"):
        text += " If you meant a different claim, just tell me."
    return text


def _choose_case(data: dict[str, Any], rctx: ResponderContext, ds: list[Directive]) -> str:
    options = data.get("options")
    if not options:
        return "Which claim are you asking about?"
    return f"Which claim are you asking about? {_numbered(options)}."


def _no_hints(data: dict[str, Any], rctx: ResponderContext, ds: list[Directive]) -> str:
    options = data.get("options")
    if not options:
        return "Which claim would you like help with?"
    return f"Which claim would you like help with? You have: {_numbered(options)}."


def _no_match(data: dict[str, Any], rctx: ResponderContext, ds: list[Directive]) -> str:
    text = "I couldn't find a claim matching that description."
    options = data.get("options")
    if options:
        text += f" Here are your claims: {_numbered(options)}."
    return text


def _no_claims(data: dict[str, Any], rctx: ResponderContext, ds: list[Directive]) -> str:
    return (
        "I don't see any claims on your policy. I can connect you with a representative, "
        "or we can end the conversation."
    )


# --- PROCESS_CASE ---------------------------------------------------------------


def _status_sentence(claim: dict[str, Any]) -> str:
    return f"Claim {claim['case_id']} is currently {claim['status']}: {claim['summary']}."


def _answer_question(data: dict[str, Any], rctx: ResponderContext, ds: list[Directive]) -> str:
    followup = data.get("followup") or {}
    facts = rctx.facts
    claim = facts.get("claim") if isinstance(facts.get("claim"), dict) else None
    intent = facts.get("turn_intent")
    parts: list[str] = []

    if followup.get("kind") == "matched" and followup.get("text"):
        parts.append(str(followup["text"]))
    elif claim is not None and intent == "denial_question" and claim.get("denial_reason"):
        parts.append(f"Claim {claim['case_id']} was denied because {claim['denial_reason']}.")
        docs = claim.get("documents_needed") or []
        if docs:
            parts.append(f"To move it forward, please send {documents_phrase(docs)}.")
    elif claim is not None and intent == "status_inquiry":
        parts.append(_status_sentence(claim))
    elif claim is not None and intent == "payment_question":
        parts.append(
            f"For claim {claim['case_id']}, the expected reimbursement is "
            f"${claim['expected_reimbursement_amount']} and the net pay is ${claim['net_pay']}."
        )
    elif followup.get("text"):
        parts.append(str(followup["text"]))
    elif claim is not None:
        parts.append(_status_sentence(claim))
    else:
        parts.append("I don't have specific information on that question.")

    alternatives = facts.get("alternatives")
    if isinstance(alternatives, dict):
        for doc, text in alternatives.items():
            if doc != "default":
                parts.append(f"For the {doc}: {text}")
        if alternatives.get("default"):
            parts.append(str(alternatives["default"]))
    return " ".join(parts)


def _deadline_passed(data: dict[str, Any], rctx: ResponderContext, ds: list[Directive]) -> str:
    deadline = data.get("deadline")
    when = f" ({deadline})" if deadline else ""
    return (
        f"The appeal deadline for this claim{when} has already passed, "
        "so a representative will need to review your options."
    )


def _no_data(data: dict[str, Any], rctx: ResponderContext, ds: list[Directive]) -> str:
    return "I don't have specific information about that in your claim record, so I won't guess."


def _docs_exhausted(data: dict[str, Any], rctx: ResponderContext, ds: list[Directive]) -> str:
    text = data.get("text")
    if text:
        return str(text)
    return "Since the alternatives haven't worked, a representative will need to review your claim."


def _anything_else(data: dict[str, Any], rctx: ResponderContext, ds: list[Directive]) -> str:
    return "Is there anything else I can help you with on this claim?"


# --- POST_PROCESS ---------------------------------------------------------------


def _offer_email(data: dict[str, Any], rctx: ResponderContext, ds: list[Directive]) -> str:
    to = data.get("to_masked")
    where = f" to {to}" if to else " to the email address on file"
    lead = (
        "I'll connect you with a representative. Before I do, w"
        if data.get("handoff_pending")
        else "W"
    )
    return f"{lead}ould you like me to email a summary of our conversation{where}?"


def _email_preview(data: dict[str, Any], rctx: ResponderContext, ds: list[Directive]) -> str:
    raw = data.get("draft")
    if not raw:
        return "Here's the summary I'll send. Shall I send it?"
    draft = raw if isinstance(raw, EmailDraft) else EmailDraft.model_validate(raw)
    return (
        f"Here's the summary I'll send to {draft.to_masked}:\n\n"
        f"Subject: {draft.subject}\n\n{draft.body}\n\nShall I send it?"
    )


def _email_sent(data: dict[str, Any], rctx: ResponderContext, ds: list[Directive]) -> str:
    to = data.get("to_masked")
    return f"Done — I've sent the summary to {to}." if to else "Done — I've sent the summary."


def _email_skipped(data: dict[str, Any], rctx: ResponderContext, ds: list[Directive]) -> str:
    return "No problem — I won't send an email summary."


def _email_restricted(data: dict[str, Any], rctx: ResponderContext, ds: list[Directive]) -> str:
    to = data.get("to_masked")
    on_file = f"the email address on file ({to})" if to else "the email address on file"
    return (
        f"For your security I can only send the summary to {on_file}; "
        "I can't send it to a different address."
    )


def _closing(data: dict[str, Any], rctx: ResponderContext, ds: list[Directive]) -> str:
    return "Thank you for contacting claims support. Take care!"


# --- Global -----------------------------------------------------------------------

_PULL_BACK: dict[Phase, str] = {
    Phase.VERIFY_ID: "To get started on your claim, I just need to verify your identity.",
    Phase.RESOLVE_INTENT: "Which of your claims can I help you with?",
    Phase.PROCESS_CASE: "Do you have any other questions about this claim?",
    Phase.POST_PROCESS: "Would you like me to send the summary email, or skip it?",
}


def _decline_off_topic(data: dict[str, Any], rctx: ResponderContext, ds: list[Directive]) -> str:
    parts = ["I can only help with insurance claims and policy questions."]
    if rctx.phase in _PULL_BACK:
        parts.append(_PULL_BACK[rctx.phase])
    if data.get("offer_handoff"):
        parts.append(_HANDOFF_OFFER)
    return " ".join(parts)


def _answer_general(data: dict[str, Any], rctx: ResponderContext, ds: list[Directive]) -> str:
    kb = data.get("kb") or {}
    question = str(data.get("question") or "").lower()
    hits = [
        f"{key.replace('_', ' ').capitalize()}: {text}"
        for key, text in kb.items()
        if key != "default_guidance" and key.replace("_", " ") in question
    ]
    if hits:
        return " ".join(hits)
    if kb.get("default_guidance"):
        return str(kb["default_guidance"])
    return "I can answer general questions about insurance claims and your policy."


def _small_talk(data: dict[str, Any], rctx: ResponderContext, ds: list[Directive]) -> str:
    return "Happy to chat for a moment — I'm here to help with your insurance claims."


def _other_party_restricted(
    data: dict[str, Any], rctx: ResponderContext, ds: list[Directive]
) -> str:
    return (
        "I can only discuss the claims on the verified policy, so I can't share anything "
        "about another person's claims."
    )


def _session_closed(data: dict[str, Any], rctx: ResponderContext, ds: list[Directive]) -> str:
    if data.get("reason") == "max_turns":
        return (
            "This conversation has reached its message limit. "
            "Please start a new chat if you need more help."
        )
    if data.get("phase") == Phase.HANDOFF.value:
        return (
            "This conversation has been handed to a representative, who will follow up with "
            "you. This chat is now closed."
        )
    return "This conversation has ended. Please start a new chat if you need more help."


TEMPLATES: dict[DirectiveKind, Template] = {
    "need_identity": _need_identity,
    "verify_failed": _verify_failed,
    "locked": _locked,
    "confirm_verified": _confirm_verified,
    "acknowledge_hint": _acknowledge_hint,
    "explain_why": _explain_why,
    "offer_alternatives": _offer_alternatives,
    "empathize": _empathize,
    "persuade": _persuade,
    "stop_persuading": _stop_persuading,
    "restate_requirement": _restate,
    "offer_handoff": _offer_handoff,
    "handoff_done": _handoff_done,
    "rep_ask_details": _rep_ask_details,
    "rep_denied": _rep_denied,
    "consent_sent": _consent_sent,
    "consent_waiting": _consent_waiting,
    "consent_approved": _consent_approved,
    "consent_expired": _consent_expired,
    "case_selected": _case_selected,
    "choose_case": _choose_case,
    "no_hints": _no_hints,
    "no_match": _no_match,
    "no_claims": _no_claims,
    "answer_question": _answer_question,
    "deadline_passed": _deadline_passed,
    "no_data": _no_data,
    "docs_exhausted": _docs_exhausted,
    "anything_else": _anything_else,
    "offer_email": _offer_email,
    "email_preview": _email_preview,
    "email_sent": _email_sent,
    "email_skipped": _email_skipped,
    "email_address_restricted": _email_restricted,
    "closing": _closing,
    "decline_off_topic": _decline_off_topic,
    "answer_general": _answer_general,
    "small_talk": _small_talk,
    "session_closed": _session_closed,
    "other_party_restricted": _other_party_restricted,
}


def render(directives: list[Directive], rctx: ResponderContext) -> str:
    out = ""
    prev_preview = False
    for d in directives:
        piece = TEMPLATES[d.kind](d.data, rctx, directives).strip()
        if not piece:
            continue
        is_preview = d.kind == "email_preview"
        if out:
            out += "\n\n" if is_preview or prev_preview else " "
        out += piece
        prev_preview = is_preview
    return out
