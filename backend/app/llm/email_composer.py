"""LLMEmailComposer: polish only the "What we discussed" section of the email draft.

The deterministic draft (``build_email_draft``) guarantees every section. The model
may only rephrase the discussed lines; its text must pass the OutputGuard against the
draft and case log, otherwise the deterministic draft is used unchanged.
"""

import json
from typing import Any

from app.data.repo import FixtureRepo
from app.guards.output_guard import check_reply
from app.llm.base import LLMError
from app.llm.client import LLMClient
from app.llm.prompts import load_prompt
from app.sop.context import ResponderContext
from app.sop.email_summary import EmailDraft
from app.sop.phases import Phase
from app.sop.state import SessionState

SECTION = "What we discussed"
_MAX_LEN = 600


class LLMEmailComposer:
    def __init__(self, client: LLMClient, repo: FixtureRepo) -> None:
        self.client = client
        self.repo = repo

    def compose(self, state: SessionState, draft: EmailDraft) -> EmailDraft:
        lines = draft.sections.get(SECTION)
        if not lines:
            return draft
        case_log = [e.model_dump(mode="json") for e in state.case_log]
        caller = [m.text for m in state.transcript if m.role == "user"]
        payload = {"discussed_lines": lines, "case_log": case_log, "caller_messages": caller}
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": load_prompt("email")},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ]
        try:
            message = self.client.chat(messages)
        except LLMError:
            return draft
        text = " ".join((getattr(message, "content", None) or "").split())
        if not text or len(text) > _MAX_LEN:
            return draft

        facts: dict[str, Any] = {"draft": draft.model_dump(), "case_log": case_log}
        rctx = ResponderContext(
            phase=Phase.POST_PROCESS,
            directives=[],
            facts=facts,
            user_text="",
            history=[],
            tool_executor=None,
            whitelist_text=json.dumps(facts) + "\n" + "\n".join(caller),
        )
        if not check_reply(text, state, rctx, self.repo).ok:
            return draft
        sections = dict(draft.sections)
        sections[SECTION] = [text]
        return draft.model_copy(update={"sections": sections})
