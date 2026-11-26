"""ContextBuilder: decide which facts the responder LLM may see this turn.

Facts are loaded by the plan's ``fact_scope``. Before access is granted
(invariant I2) only field names, counts and the caller's own hints are loaded,
whatever scope the plan asks for, and ``assert_no_record_data`` checks it.
"""

import json
import re
from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Any

from app.data.repo import Claim, FixtureRepo
from app.sop.phases import Phase
from app.sop.plan import Directive, FactScope, PolicyCtx, TurnPlan
from app.sop.state import Message, SessionState
from app.tools.claims import claim_summary_line
from app.tools.guidance import deadline_fact, document_requirements
from app.tools.registry import execute_tool

HISTORY_LEN = 6
# Case slots that are the caller's own words; never identity values or a case_id.
_USER_HINT_SLOTS = ("case_type", "status", "month", "year", "case_quote")
_ACCESS_SCOPES: frozenset[FactScope] = frozenset({"claims_summary", "case", "email"})

ToolExecutor = Callable[[str, dict[str, Any]], dict[str, Any]]


@dataclass
class ResponderContext:
    phase: Phase
    directives: list[Directive]
    facts: dict[str, Any]
    user_text: str
    history: list[Message]
    tool_executor: ToolExecutor | None
    # Facts JSON plus everything the user said; the responder appends each tool result.
    whitelist_text: str


def build_context(
    state: SessionState, plan: TurnPlan, ctx: PolicyCtx, user_text: str
) -> ResponderContext:
    scope: FactScope = plan.fact_scope
    if scope in _ACCESS_SCOPES and not state.access_granted:
        scope = "none"

    facts: dict[str, Any] | None = None
    if scope == "claims_summary":
        facts = _claims_summary_facts(state, ctx)
    elif scope == "case":
        facts = _case_facts(state, plan, ctx)
    elif scope == "email":
        preview = state.email.preview
        facts = {"draft": preview.model_dump() if preview is not None else None}
    if facts is None:
        scope = "none"
        facts = _pre_access_facts(state, ctx)

    user_corpus = "\n".join([*(m.text for m in state.transcript if m.role == "user"), user_text])
    if not state.access_granted:
        assert_no_record_data(facts, ctx.repo, user_corpus)

    tool_executor: ToolExecutor | None = None
    if scope == "case" and state.access_granted:

        def tool_executor(name: str, args: dict[str, Any]) -> dict[str, Any]:
            return execute_tool(name, args, state, ctx)

    return ResponderContext(
        phase=state.phase,
        directives=list(plan.directives),
        facts=facts,
        user_text=user_text,
        history=list(state.transcript[-HISTORY_LEN:]),
        tool_executor=tool_executor,
        whitelist_text=json.dumps(facts) + "\n" + user_corpus,
    )


def _pre_access_facts(state: SessionState, ctx: PolicyCtx) -> dict[str, Any]:
    identity = state.identity
    needed = max(0, ctx.sop.verification.min_matched_fields - identity.provided_count())
    hints = {k: v for k in _USER_HINT_SLOTS if (v := state.memory.get(k)) is not None}
    return {
        "needed": needed,
        "options": list(identity.remaining_options()),
        "user_hints": hints,
    }


def _claims_summary_facts(state: SessionState, ctx: PolicyCtx) -> dict[str, Any] | None:
    if state.verified_party_id is None:
        return None
    claims = ctx.repo.claims_for(state.verified_party_id)
    return {"claims": [claim_summary_line(c) for c in claims]}


def _active_claim(state: SessionState, repo: FixtureRepo) -> Claim | None:
    if state.verified_party_id is None or state.active_case_id is None:
        return None
    for claim in repo.claims_for(state.verified_party_id):
        if claim.case_id == state.active_case_id:
            return claim
    return None


def _case_facts(state: SessionState, plan: TurnPlan, ctx: PolicyCtx) -> dict[str, Any] | None:
    claim = _active_claim(state, ctx.repo)
    if claim is None:
        return None
    repo = ctx.repo
    deadline = deadline_fact(claim, ctx.today)
    requirements = document_requirements(repo, claim, ctx.sop.process.doc_fuzzy_threshold)
    facts: dict[str, Any] = {
        "claim": claim.model_dump(mode="json", exclude={"party_id"}),
        "field_definitions": {
            name: str(node["description"])
            for name, node in repo.claim_schema["field_descriptions"].items()
        },
        "deadline": (
            {
                "deadline": deadline.deadline.isoformat(),
                "days_left": deadline.days_left,
                "passed": deadline.passed,
            }
            if deadline is not None
            else None
        ),
        "doc_requirements": asdict(requirements),
    }
    answer = next((d for d in reversed(plan.directives) if d.kind == "answer_question"), None)
    if answer is not None:
        if "followup" in answer.data:
            facts["followup"] = answer.data["followup"]
        if "alternatives" in answer.data:
            facts["alternatives"] = answer.data["alternatives"]
    return facts


def _record_terms(repo: FixtureRepo) -> tuple[list[str], list[str]]:
    """(substring terms, whole-token terms) that are record data."""
    terms = [c.case_id for c in repo.claims]
    tokens: list[str] = []
    for holder in repo.policyholders:
        terms += [holder.phone, *holder.phone_aliases, holder.email, *holder.email_aliases]
        terms.append(holder.dob.isoformat())
        tokens.append(holder.id_last4)
    return terms, tokens


def assert_no_record_data(facts: dict[str, Any], repo: FixtureRepo, user_corpus: str = "") -> None:
    """Raise AssertionError if the facts carry any claim or policyholder record value.

    A value the caller typed themselves (it appears in ``user_corpus``) is not a leak.
    """
    blob = json.dumps(facts).lower()
    corpus = user_corpus.lower()
    terms, tokens = _record_terms(repo)
    for term in terms:
        t = term.lower()
        if t in blob and t not in corpus:
            raise AssertionError("record data in pre-access facts")
    for token in tokens:
        if re.search(rf"\b{re.escape(token)}\b", blob) and token not in corpus:
            raise AssertionError("record data in pre-access facts")
