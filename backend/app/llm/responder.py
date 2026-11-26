"""LLMResponder: phrase the code-decided directives as one natural reply.

The model sees the shared system prompt plus the phase's guidance, the FACTS the
ContextBuilder allowed, the numbered DIRECTIVES and recent history. In PROCESS_CASE,
when the provider supports tools, it may call the read-only tools a bounded number of
times; every result is appended to the guard's whitelist so the reply can cite it.
"""

import json
from typing import Any

from app.llm.base import LLMError
from app.llm.client import LLMClient
from app.llm.prompts import load_prompt
from app.sop.context import ResponderContext
from app.sop.phases import Phase
from app.sop.plan import Directive
from app.sop.state import Message
from app.tools.registry import TOOL_SPECS

_PHASE_PROMPTS: dict[Phase, str] = {
    Phase.VERIFY_ID: "respond_verify",
    Phase.RESOLVE_INTENT: "respond_resolve",
    Phase.PROCESS_CASE: "respond_process",
    Phase.POST_PROCESS: "respond_post",
    Phase.HANDOFF: "respond_post",
    Phase.CLOSED: "respond_post",
}
_ROLES = {"user": "user", "agent": "assistant"}


def system_prompt(phase: Phase) -> str:
    return load_prompt("system") + "\n\n" + load_prompt(_PHASE_PROMPTS[phase])


def context_message(facts: dict[str, Any], directives: list[Directive]) -> str:
    lines = [f"FACTS:\n{json.dumps(facts, ensure_ascii=False)}", "", "DIRECTIVES:"]
    for i, d in enumerate(directives, start=1):
        data = f" {json.dumps(d.data, ensure_ascii=False, default=str)}" if d.data else ""
        lines.append(f"{i}. {d.kind}{data}")
    if not directives:
        lines.append("(none: reply briefly and helpfully to the caller's message)")
    return "\n".join(lines)


def directives_reminder(directives: list[Directive]) -> str:
    kinds = ", ".join(f"{i}. {d.kind}" for i, d in enumerate(directives, start=1))
    return f"Current DIRECTIVES, in order: {kinds or '(none)'}."


def _history(history: list[Message], user_text: str) -> list[dict[str, Any]]:
    turns = [m for m in history if m.role in _ROLES]
    # The engine records the latest user message before building the context; it is
    # appended separately, last, so drop it from the history.
    if turns and turns[-1].role == "user" and turns[-1].text == user_text:
        turns = turns[:-1]
    return [{"role": _ROLES[m.role], "content": m.text} for m in turns]


def _tool_args(raw: str | None) -> dict[str, Any]:
    try:
        args = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {}
    return args if isinstance(args, dict) else {}


class LLMResponder:
    def __init__(self, client: LLMClient, max_tool_iterations: int) -> None:
        self.client = client
        self.max_tool_iterations = max_tool_iterations

    def respond(self, rctx: ResponderContext, feedback: list[str] | None = None) -> str:
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt(rctx.phase)},
            {"role": "system", "content": context_message(rctx.facts, rctx.directives)},
            *_history(rctx.history, rctx.user_text),
            {"role": "system", "content": directives_reminder(rctx.directives)},
        ]
        if rctx.user_text.strip():
            messages.append({"role": "user", "content": rctx.user_text})
        if feedback:
            messages.append(
                {
                    "role": "system",
                    "content": f"Your previous draft violated: {', '.join(feedback)}. "
                    "Rewrite without those problems.",
                }
            )

        executor = rctx.tool_executor
        use_tools = executor is not None and self.client.config.supports_tools
        rounds = 0
        while True:
            tools = TOOL_SPECS if use_tools and rounds < self.max_tool_iterations else None
            message = self.client.chat(messages, tools=tools)
            calls = list(getattr(message, "tool_calls", None) or [])
            if tools is None or not calls or executor is None:
                break
            rounds += 1
            messages.append(
                {
                    "role": "assistant",
                    "content": message.content,
                    "tool_calls": [call.model_dump(mode="json") for call in calls],
                }
            )
            for call in calls:
                function = getattr(call, "function", None)
                if function is None:
                    result: dict[str, Any] = {"error": "unknown_tool"}
                else:
                    result = executor(function.name, _tool_args(function.arguments))
                content = json.dumps(result, ensure_ascii=False)
                messages.append({"role": "tool", "tool_call_id": call.id, "content": content})
                rctx.whitelist_text += "\n" + content

        text = (getattr(message, "content", None) or "").strip()
        if not text:
            raise LLMError("other", "Empty reply from model")
        return text
