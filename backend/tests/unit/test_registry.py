import json

from app.data.repo import FixtureRepo
from app.settings import SopConfig
from app.sop.phases import Phase, SubState
from app.sop.state import SessionState
from app.tools.guidance import GuidanceTopic
from app.tools.registry import TOOL_SPECS, execute_tool
from tests.fakes import make_ctx

NOT_PERMITTED = {"error": "not_permitted"}


def _state(party: str = "P9") -> SessionState:
    s = SessionState.new("s1")
    s.phase = Phase.PROCESS_CASE
    s.sub_state = SubState.ACTIVE
    s.verified_party_id = party
    s.access_granted = True
    s.active_case_id = "CL-2048"
    return s


def test_tool_specs_shape() -> None:
    names = [spec["function"]["name"] for spec in TOOL_SPECS]
    assert names == [
        "get_document_requirements",
        "get_document_alternatives",
        "get_followup_guidance",
        "get_field_definition",
    ]
    for spec in TOOL_SPECS:
        assert spec["type"] == "function"
        params = spec["function"]["parameters"]
        assert params["type"] == "object"
        assert params["additionalProperties"] is False
    followup = TOOL_SPECS[2]["function"]["parameters"]
    assert followup["required"] == ["case_id"]
    assert set(followup["properties"]["topic"]["enum"]) == set(GuidanceTopic.__args__)
    json.dumps(TOOL_SPECS)


def test_registry_denies_before_access(repo: FixtureRepo, sop: SopConfig) -> None:
    s = _state()
    s.access_granted = False
    ctx = make_ctx(repo, sop)
    assert execute_tool("get_document_requirements", {"case_id": "CL-2048"}, s, ctx) == (
        NOT_PERMITTED
    )
    assert execute_tool("get_field_definition", {"field": "net_pay"}, s, ctx) == NOT_PERMITTED


def test_registry_denies_outside_process_phase(repo: FixtureRepo, sop: SopConfig) -> None:
    s = _state()
    s.phase = Phase.RESOLVE_INTENT
    ctx = make_ctx(repo, sop)
    result = execute_tool("get_followup_guidance", {"case_id": "CL-2048"}, s, ctx)
    assert result == NOT_PERMITTED


def test_registry_denies_other_party_case(repo: FixtureRepo, sop: SopConfig) -> None:
    s = _state()
    ctx = make_ctx(repo, sop)
    for name in ("get_document_requirements", "get_document_alternatives"):
        assert execute_tool(name, {"case_id": "CL-3001"}, s, ctx) == NOT_PERMITTED
    assert execute_tool("get_followup_guidance", {"case_id": "CL-3001"}, s, ctx) == NOT_PERMITTED
    assert execute_tool("get_followup_guidance", {"case_id": "CL-9999"}, s, ctx) == NOT_PERMITTED


def test_registry_unknown_tool(repo: FixtureRepo, sop: SopConfig) -> None:
    result = execute_tool("delete_claim", {"case_id": "CL-2048"}, _state(), make_ctx(repo, sop))
    assert result == {"error": "unknown_tool"}


def test_registry_followup_ok(repo: FixtureRepo, sop: SopConfig) -> None:
    s = _state()
    ctx = make_ctx(repo, sop, user_text="how do i submit?")
    result = execute_tool("get_followup_guidance", {"case_id": "CL-2048"}, s, ctx)
    assert result["kind"] == "matched"
    assert result["topic"] == "submission_method"
    assert "CL-2048" in result["text"]
    json.dumps(result)


def test_registry_followup_topic_and_invalid_topic(repo: FixtureRepo, sop: SopConfig) -> None:
    s = _state()
    ctx = make_ctx(repo, sop, user_text="hmm")
    picked = execute_tool(
        "get_followup_guidance", {"case_id": "CL-2048", "topic": "receipt_confirmation"}, s, ctx
    )
    assert picked["topic"] == "receipt_confirmation"
    bogus = execute_tool("get_followup_guidance", {"case_id": "CL-2048", "topic": "bogus"}, s, ctx)
    assert bogus["kind"] == "fallback"


def test_registry_document_tools(repo: FixtureRepo, sop: SopConfig) -> None:
    s = _state()
    ctx = make_ctx(repo, sop)
    reqs = execute_tool("get_document_requirements", {"case_id": "CL-2048"}, s, ctx)
    assert set(reqs) == {"default", "case_type", "per_document"}
    assert set(reqs["per_document"]) == {"pathology report", "office note"}
    alts = execute_tool(
        "get_document_alternatives", {"case_id": "CL-2048", "document": "office note"}, s, ctx
    )
    assert set(alts["alternatives"]) == {"office note", "default"}
    json.dumps([reqs, alts])


def test_registry_field_definition(repo: FixtureRepo, sop: SopConfig) -> None:
    ctx = make_ctx(repo, sop)
    result = execute_tool("get_field_definition", {"field": "net_pay"}, _state(), ctx)
    assert result["field"] == "net_pay"
    assert isinstance(result["definition"], str) and result["definition"]
    missing = execute_tool("get_field_definition", {"field": "nope"}, _state(), ctx)
    assert missing == {"field": "nope", "definition": None}
