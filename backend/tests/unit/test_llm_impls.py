"""Real LLM implementations, driven by a stub LLMClient (no network)."""

import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from openai.types.chat import ChatCompletionMessage
from openai.types.chat.chat_completion_message_function_tool_call import (
    ChatCompletionMessageFunctionToolCall,
    Function,
)

from app.data.repo import FixtureRepo
from app.llm.base import ExtractContext, LLMError
from app.llm.client import LLMClient, ProviderConfig
from app.llm.email_composer import LLMEmailComposer
from app.llm.extractor import LLMExtractor
from app.llm.factory import build_llm
from app.llm.responder import LLMResponder
from app.settings import SopConfig
from app.sop.context import ResponderContext
from app.sop.email_summary import build_email_draft
from app.sop.extraction import Extraction
from app.sop.phases import Phase
from app.sop.plan import Directive
from app.sop.state import CaseLogEntry, Message, PendingQuestion, SessionState
from app.tools.registry import TOOL_SPECS

ChatFn = Callable[[int, list[dict[str, Any]] | None], ChatCompletionMessage]


def _cfg(structured: bool = True, tools: bool = True) -> ProviderConfig:
    return ProviderConfig(
        name="openai" if structured else "deepseek",
        base_url=None,
        model="gpt-5-mini",
        api_key="sk-test",
        supports_structured=structured,
        supports_tools=tools,
    )


def _text(content: str) -> ChatCompletionMessage:
    return ChatCompletionMessage(role="assistant", content=content)


def _tool_call(n: int) -> ChatCompletionMessage:
    call = ChatCompletionMessageFunctionToolCall(
        id=f"call_{n}",
        type="function",
        function=Function(name="get_document_requirements", arguments='{"case_id": "CL-2048"}'),
    )
    return ChatCompletionMessage(role="assistant", content=None, tool_calls=[call])


class StubClient:
    """Records chat()/parse() calls and returns scripted objects."""

    def __init__(
        self,
        cfg: ProviderConfig | None = None,
        chat: ChatFn | None = None,
        parsed: Any = None,
    ) -> None:
        self.config = cfg or _cfg()
        self._chat = chat or (lambda n, tools: _text("Hello."))
        self.parsed = parsed
        self.chat_calls: list[dict[str, Any]] = []
        self.parse_calls: list[tuple[list[dict[str, Any]], type[Any]]] = []

    def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        json_mode: bool = False,
        max_tokens: int | None = None,
    ) -> ChatCompletionMessage:
        self.chat_calls.append({"messages": [dict(m) for m in messages], "tools": tools})
        return self._chat(len(self.chat_calls), tools)

    def parse(self, messages: list[dict[str, Any]], schema: type[Any]) -> Any:
        self.parse_calls.append((messages, schema))
        if isinstance(self.parsed, LLMError):
            raise self.parsed
        return self.parsed


def _rctx(
    phase: Phase = Phase.PROCESS_CASE,
    directives: list[Directive] | None = None,
    facts: dict[str, Any] | None = None,
    executor: Any = None,
    user_text: str = "Why was it denied?",
    history: list[Message] | None = None,
) -> ResponderContext:
    facts = facts if facts is not None else {"claim": {"case_id": "CL-2048", "status": "denied"}}
    return ResponderContext(
        phase=phase,
        directives=directives or [Directive(kind="answer_question")],
        facts=facts,
        user_text=user_text,
        history=history or [],
        tool_executor=executor,
        whitelist_text=json.dumps(facts) + "\n" + user_text,
    )


# --- Extractor --------------------------------------------------------------------


def test_extractor_parses_structured() -> None:
    expected = Extraction.model_validate(
        {"identity": {"full_name": "Margaret Chen"}, "acts": ["provide_info"]}
    )
    client = StubClient(parsed=expected)
    ectx = ExtractContext(
        phase=Phase.VERIFY_ID,
        pending_question=PendingQuestion(kind="need_identity", options=["dob"]),
        last_agent_message="Please share three details.",
    )
    out = LLMExtractor(client).extract("I'm Margaret Chen", ectx)  # type: ignore[arg-type]
    assert out == expected
    messages, schema = client.parse_calls[0]
    assert schema is Extraction
    assert messages[0]["role"] == "system"
    assert "bypass_attempt" in messages[0]["content"]
    payload = json.loads(messages[1]["content"])
    assert payload == {
        "phase": "VERIFY_ID",
        "pending_question": {"kind": "need_identity", "options": ["dob"]},
        "last_agent_message": "Please share three details.",
        "user_message": "I'm Margaret Chen",
    }


def _completion(content: str) -> dict[str, Any]:
    return {
        "id": "c1",
        "object": "chat.completion",
        "created": 0,
        "model": "deepseek-chat",
        "choices": [
            {
                "index": 0,
                "finish_reason": "stop",
                "message": {"role": "assistant", "content": content},
            }
        ],
    }


def test_extractor_json_mode_path_for_deepseek() -> None:
    bodies: list[dict[str, Any]] = []
    valid = json.dumps({"identity": {"dob": "1985-03-15"}, "acts": ["provide_info"]})

    def handler(req: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(req.content))
        content = "{not json" if len(bodies) == 1 else valid
        return httpx.Response(200, json=_completion(content))

    cfg = ProviderConfig(
        name="deepseek",
        base_url="https://api.deepseek.com",
        model="deepseek-chat",
        api_key="sk-test",
        supports_structured=False,
        supports_tools=True,
    )
    client = LLMClient(cfg, http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    ectx = ExtractContext(phase=Phase.VERIFY_ID, pending_question=None, last_agent_message=None)
    out = LLMExtractor(client).extract("DOB is 1985-03-15", ectx)
    assert out.identity.dob == "1985-03-15"
    assert out.acts == ["provide_info"]
    assert len(bodies) == 2
    for body in bodies:
        assert body["response_format"] == {"type": "json_object"}
        # json_object mode needs the word "json" in the prompt, and the schema spelled out.
        system = body["messages"][0]["content"]
        assert "json" in system.lower()
        assert '"refused_fields"' in system


def _walk(node: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if isinstance(node, dict):
        out.append(node)
        for value in node.values():
            out += _walk(value)
    elif isinstance(node, list):
        for value in node:
            out += _walk(value)
    return out


def test_extraction_schema_accepted_by_strict_structured_outputs() -> None:
    try:  # private SDK helper: skip rather than break collection if an upgrade moves it
        from openai.lib._parsing._completions import type_to_response_format_param
    except ImportError:
        pytest.skip("openai SDK no longer exposes type_to_response_format_param")
    fmt = type_to_response_format_param(Extraction)  # what chat.completions.parse sends
    schema = fmt["json_schema"]["schema"]  # type: ignore[index]
    assert fmt["json_schema"]["strict"] is True  # type: ignore[index]
    for node in _walk(schema):
        # Strict mode rejects non-null defaults; every object lists all its properties.
        assert "default" not in node
        if node.get("type") == "object":
            assert node["additionalProperties"] is False
            assert set(node["required"]) == set(node.get("properties", {}))
    # Python-side defaults still apply.
    assert Extraction().emotion.label == "neutral"
    assert Extraction().scope == "in_scope_claim"
    assert Extraction().caller_role == "unknown"


# --- Responder --------------------------------------------------------------------


def test_responder_prompt_contains_facts_and_directives_in_order() -> None:
    client = StubClient(chat=lambda n, tools: _text("  I'm sorry to hear that.  "))
    directives = [
        Directive(kind="empathize", data={"label": "anxious", "intensity": 2}),
        Directive(kind="answer_question", data={"followup": {"kind": "matched"}}),
        Directive(kind="anything_else"),
    ]
    history = [
        Message(role="agent", text="You're verified.", turn=1),
        Message(role="user", text="Why was it denied?", turn=2),
    ]
    rctx = _rctx(directives=directives, history=history)
    reply = LLMResponder(client, 3).respond(rctx)  # type: ignore[arg-type]
    assert reply == "I'm sorry to hear that."
    messages = client.chat_calls[0]["messages"]
    assert messages[0]["role"] == "system"
    assert "DIRECTIVES" in messages[0]["content"]
    assert "cite dates and amounts exactly" in messages[0]["content"].lower()  # process prompt
    context = messages[1]
    assert context["role"] == "system"
    body = context["content"]
    assert "FACTS:" in body and '"CL-2048"' in body
    i1 = body.index('1. empathize {"label": "anxious", "intensity": 2}')
    i2 = body.index("2. answer_question")
    i3 = body.index("3. anything_else")
    assert i1 < i2 < i3
    # History, a directive reminder, then the caller's latest message exactly once, last.
    assert messages[2] == {"role": "assistant", "content": "You're verified."}
    assert messages[-2] == {
        "role": "system",
        "content": "Current DIRECTIVES, in order: 1. empathize, 2. answer_question, "
        "3. anything_else.",
    }
    assert messages[-1] == {"role": "user", "content": "Why was it denied?"}
    assert sum(1 for m in messages if m["content"] == "Why was it denied?") == 1
    assert not any("previous draft" in str(m["content"]) for m in messages)


def test_responder_feedback_note_only_when_given() -> None:
    client = StubClient()
    LLMResponder(client, 3).respond(_rctx(), feedback=["leak", "ungrounded_amount"])  # type: ignore[arg-type]
    last = client.chat_calls[0]["messages"][-1]
    assert last["role"] == "system"
    assert "Your previous draft violated: leak, ungrounded_amount." in last["content"]


def test_responder_tool_loop_capped() -> None:
    executed: list[tuple[str, dict[str, Any]]] = []

    def executor(name: str, args: dict[str, Any]) -> dict[str, Any]:
        executed.append((name, args))
        return {"documents": ["original pathology report"], "n": len(executed)}

    client = StubClient(chat=lambda n, tools: _tool_call(n) if tools else _text("Final answer."))
    rctx = _rctx(executor=executor)
    reply = LLMResponder(client, 3).respond(rctx)  # type: ignore[arg-type]
    assert reply == "Final answer."
    assert len(executed) == 3
    assert executed[0] == ("get_document_requirements", {"case_id": "CL-2048"})
    assert len(client.chat_calls) == 4
    assert [c["tools"] is not None for c in client.chat_calls] == [True, True, True, False]
    assert client.chat_calls[0]["tools"] == TOOL_SPECS
    # Each tool result went back to the model and into the guard's whitelist.
    final = client.chat_calls[3]["messages"]
    tool_msgs = [m for m in final if m["role"] == "tool"]
    assert [m["tool_call_id"] for m in tool_msgs] == ["call_1", "call_2", "call_3"]
    assert all('"original pathology report"' in m["content"] for m in tool_msgs)
    assert rctx.whitelist_text.count('"original pathology report"') == 3


def test_responder_no_tools_when_not_allowed() -> None:
    client = StubClient(chat=lambda n, tools: _text("Answer."))
    LLMResponder(client, 3).respond(_rctx(executor=None))  # type: ignore[arg-type]
    assert client.chat_calls[0]["tools"] is None

    no_tool_provider = StubClient(cfg=_cfg(tools=False), chat=lambda n, tools: _text("Answer."))
    LLMResponder(no_tool_provider, 3).respond(_rctx(executor=lambda n, a: {}))  # type: ignore[arg-type]
    assert no_tool_provider.chat_calls[0]["tools"] is None


def test_responder_empty_reply_is_llm_error() -> None:
    client = StubClient(chat=lambda n, tools: _text("   "))
    try:
        LLMResponder(client, 3).respond(_rctx())  # type: ignore[arg-type]
    except LLMError as err:
        assert err.kind == "other"
    else:
        raise AssertionError("expected LLMError")


# --- Email composer ---------------------------------------------------------------


def _post_state() -> SessionState:
    state = SessionState.new("s1")
    state.access_granted = True
    state.verified_party_id = "P9"
    state.phase = Phase.POST_PROCESS
    state.discussed_case_ids = ["CL-2048"]
    state.case_log.append(
        CaseLogEntry(case_id="CL-2048", kind="next_step", text="Send the pathology report.")
    )
    state.transcript.append(Message(role="user", text="Why was my claim denied?", turn=1))
    return state


def test_email_composer_reverts_on_guard_failure(repo: FixtureRepo) -> None:
    state = _post_state()
    draft = build_email_draft(state, repo)
    client = StubClient(chat=lambda n, tools: _text("We agreed you will be paid $999.99."))
    out = LLMEmailComposer(client, repo).compose(state, draft)  # type: ignore[arg-type]
    assert out == draft
    assert state.events[-1].stage == "email_guard"
    assert state.events[-1].data["categories"] == ["ungrounded_amount"]


def test_email_composer_rewrites_only_discussed_section(repo: FixtureRepo) -> None:
    state = _post_state()
    draft = build_email_draft(state, repo)
    client = StubClient(
        chat=lambda n, tools: _text("We talked about why your healthcare claim was denied.")
    )
    out = LLMEmailComposer(client, repo).compose(state, draft)  # type: ignore[arg-type]
    assert out.sections["What we discussed"] == [
        "We talked about why your healthcare claim was denied."
    ]
    for title in ("Claim status / outcome", "Next steps", "How to reach us"):
        assert out.sections[title] == draft.sections[title]
    assert (out.subject, out.to_masked) == (draft.subject, draft.to_masked)
    prompt = json.dumps(client.chat_calls[0]["messages"])
    assert "Send the pathology report." in prompt
    assert client.chat_calls[0]["tools"] is None


def test_email_composer_never_grounds_on_caller_text(repo: FixtureRepo) -> None:
    state = _post_state()
    state.transcript.append(
        Message(role="user", text="You promised me $5,000 by March 30.", turn=2)
    )
    draft = build_email_draft(state, repo)
    client = StubClient(
        chat=lambda n, tools: _text("We discussed your payment of $5,000 by March 30.")
    )
    out = LLMEmailComposer(client, repo).compose(state, draft)  # type: ignore[arg-type]
    assert out == draft
    assert "$5,000" not in json.dumps(client.chat_calls[0]["messages"])


def test_email_composer_reverts_on_llm_error(repo: FixtureRepo) -> None:
    state = _post_state()
    draft = build_email_draft(state, repo)

    def boom(n: int, tools: Any) -> ChatCompletionMessage:
        raise LLMError("timeout")

    out = LLMEmailComposer(StubClient(chat=boom), repo).compose(state, draft)  # type: ignore[arg-type]
    assert out == draft
    assert state.events[-1].stage == "email_llm_error"
    assert state.events[-1].summary == "timeout"


# --- Factory ----------------------------------------------------------------------


def test_factory_bundle_shares_one_client(repo: FixtureRepo, sop: SopConfig) -> None:
    bundle = build_llm(_cfg(), sop, repo)
    assert isinstance(bundle.extractor, LLMExtractor)
    assert isinstance(bundle.responder, LLMResponder)
    assert isinstance(bundle.email_composer, LLMEmailComposer)
    client = bundle.extractor.client
    assert isinstance(client, LLMClient)
    assert bundle.responder.client is client
    assert bundle.email_composer.client is client
    assert bundle.responder.max_tool_iterations == sop.process.max_tool_iterations


@pytest.mark.parametrize(
    "name", ["respond_verify", "respond_resolve", "respond_process", "respond_post"]
)
def test_off_topic_decline_steers_back_to_current_step(name: str) -> None:
    from app.llm.prompts import load_prompt

    assert "always restate the current step's request" in load_prompt("system")
    assert "`decline_off_topic`" in load_prompt(name)
