"""Read-only tools the responder LLM may call during PROCESS_CASE.

Permissions are enforced here in code (invariant I3): the session must have
access granted, be in PROCESS_CASE, and the case must belong to the verified
party. No tool changes session state.
"""

from dataclasses import asdict
from typing import Any, cast, get_args

from app.data.repo import Claim
from app.sop.phases import Phase
from app.sop.plan import PolicyCtx
from app.sop.state import SessionState
from app.tools.guidance import (
    GuidanceTopic,
    document_alternatives,
    document_requirements,
    field_definition,
    match_followup,
)

_TOPICS: tuple[str, ...] = get_args(GuidanceTopic)
_CASE_ID = {"type": "string", "description": "The claim's case ID, e.g. CL-1234."}


def _spec(
    name: str, description: str, properties: dict[str, Any], required: list[str]
) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
                "additionalProperties": False,
            },
        },
    }


TOOL_SPECS: list[dict[str, Any]] = [
    _spec(
        "get_document_requirements",
        "Submission guidance for the documents this claim still needs.",
        {"case_id": _CASE_ID},
        ["case_id"],
    ),
    _spec(
        "get_document_alternatives",
        "What the caller can submit instead when a required document cannot be obtained.",
        {
            "case_id": _CASE_ID,
            "document": {
                "type": "string",
                "description": "The document the caller cannot obtain; omit for all.",
            },
        },
        ["case_id"],
    ),
    _spec(
        "get_followup_guidance",
        "Approved follow-up guidance for the caller's latest question about this claim.",
        {
            "case_id": _CASE_ID,
            "topic": {
                "type": "string",
                "enum": list(_TOPICS),
                "description": "Guidance topic, if the question clearly fits one.",
            },
        },
        ["case_id"],
    ),
    _spec(
        "get_field_definition",
        "What a claim record field means.",
        {"field": {"type": "string", "description": "Claim field name, e.g. net_pay."}},
        ["field"],
    ),
]


class ToolPermissionError(Exception):
    pass


def execute_tool(
    name: str, args: dict[str, Any], state: SessionState, ctx: PolicyCtx
) -> dict[str, Any]:
    handler = _HANDLERS.get(name)
    if handler is None:
        return {"error": "unknown_tool"}
    try:
        return handler(args, state, ctx)
    except ToolPermissionError:
        return {"error": "not_permitted"}


def _check_session(state: SessionState) -> None:
    if not state.access_granted or state.phase != Phase.PROCESS_CASE:
        raise ToolPermissionError


def _owned_case(args: dict[str, Any], state: SessionState, ctx: PolicyCtx) -> Claim:
    _check_session(state)
    case_id = args.get("case_id")
    if not state.verified_party_id or not isinstance(case_id, str):
        raise ToolPermissionError
    for claim in ctx.repo.claims_for(state.verified_party_id):
        if claim.case_id == case_id.strip():
            return claim
    raise ToolPermissionError


def _optional_str(args: dict[str, Any], key: str) -> str | None:
    value = args.get(key)
    return value if isinstance(value, str) and value.strip() else None


def _document_requirements(
    args: dict[str, Any], state: SessionState, ctx: PolicyCtx
) -> dict[str, Any]:
    case = _owned_case(args, state, ctx)
    return asdict(document_requirements(ctx.repo, case, ctx.sop.process.doc_fuzzy_threshold))


def _document_alternatives(
    args: dict[str, Any], state: SessionState, ctx: PolicyCtx
) -> dict[str, Any]:
    case = _owned_case(args, state, ctx)
    alternatives = document_alternatives(
        ctx.repo, case, _optional_str(args, "document"), ctx.sop.process.doc_fuzzy_threshold
    )
    return {"alternatives": alternatives}


def _followup_guidance(args: dict[str, Any], state: SessionState, ctx: PolicyCtx) -> dict[str, Any]:
    case = _owned_case(args, state, ctx)
    raw = _optional_str(args, "topic")
    topic = cast(GuidanceTopic, raw) if raw in _TOPICS else None
    return asdict(match_followup(ctx.repo, case, ctx.user_text, state.turn_intent, topic))


def _field_definition(args: dict[str, Any], state: SessionState, ctx: PolicyCtx) -> dict[str, Any]:
    _check_session(state)
    field = _optional_str(args, "field") or ""
    return {"field": field, "definition": field_definition(ctx.repo, field)}


_HANDLERS = {
    "get_document_requirements": _document_requirements,
    "get_document_alternatives": _document_alternatives,
    "get_followup_guidance": _followup_guidance,
    "get_field_definition": _field_definition,
}
