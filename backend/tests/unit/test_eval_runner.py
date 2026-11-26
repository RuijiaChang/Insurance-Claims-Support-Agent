from datetime import date
from pathlib import Path

from app.sop.engine import Engine
from app.tools.email import Outbox
from evals.run_evals import Scenario, load_scenarios, run_scenario
from tests.fakes import make_bundle


def test_eight_live_scenarios_have_assertions():
    scenarios = load_scenarios(Path("evals/scenarios"))
    assert len(scenarios) == 8
    assert len({s.name for s in scenarios}) == 8
    assert all(s.turns and s.expect.final_phase for s in scenarios)


def test_eval_fails_on_llm_fallback_even_when_phase_matches(repo, sop):
    scenario = Scenario.model_validate(
        {
            "name": "failure",
            "turns": [{"text": "Hello"}],
            "expect": {"final_phase": "VERIFY_ID"},
        }
    )
    result = run_scenario(
        scenario, Engine(repo, sop, date(2026, 3, 5), Outbox()), make_bundle({}, raise_kind="auth")
    )
    assert not result.passed
    assert result.llm_errors == 1


def test_eval_checks_each_turn_and_final_outbox(repo, sop):
    scenario = Scenario.model_validate(
        {
            "name": "assertions",
            "turns": [{"text": "Hello", "expect": {"phase": "PROCESS_CASE"}}],
            "expect": {"final_phase": "VERIFY_ID", "outbox_count": 1},
        }
    )
    result = run_scenario(scenario, Engine(repo, sop, date(2026, 3, 5), Outbox()), make_bundle({}))
    assert not result.passed
    assert any("turn 1" in error for error in result.failures)
    assert any("outbox_count" in error for error in result.failures)


def test_eval_poll_uses_deterministic_bundle(repo, sop):
    scenario = Scenario.model_validate(
        {
            "name": "poll",
            "turns": [{"event": "consent_poll"}],
            "expect": {"final_phase": "VERIFY_ID"},
        }
    )
    result = run_scenario(
        scenario, Engine(repo, sop, date(2026, 3, 5), Outbox()), make_bundle({}, raise_kind="auth")
    )
    assert result.passed


def test_eval_fails_when_guard_had_to_correct_ungrounded_output(repo, sop):
    from app.sop.state import TraceEvent

    class ViolationEngine(Engine):
        def handle_turn(self, state, llm, **kwargs):
            out = super().handle_turn(state, llm, **kwargs)
            state.events.append(
                TraceEvent(
                    turn=1,
                    stage="guard",
                    summary="violations: 1 (attempt 1)",
                    data={"categories": ["ungrounded_date"]},
                )
            )
            return out

    scenario = Scenario.model_validate(
        {"name": "guard", "turns": [{"text": "Hello"}], "expect": {"final_phase": "VERIFY_ID"}}
    )
    result = run_scenario(
        scenario, ViolationEngine(repo, sop, date(2026, 3, 5), Outbox()), make_bundle({})
    )
    assert result.guard_retries == 1
    assert not result.passed


def test_eval_checks_outbox_content(repo, sop):
    scenario = Scenario.model_validate(
        {
            "name": "email",
            "turns": [{"text": "Hello"}],
            "expect": {"final_phase": "VERIFY_ID", "outbox_contains": ["CL-2048", "CL-2102"]},
        }
    )
    result = run_scenario(scenario, Engine(repo, sop, date(2026, 3, 5), Outbox()), make_bundle({}))
    assert not result.passed
    assert any("outbox" in failure for failure in result.failures)
