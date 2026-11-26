"""Run YAML conversations against a real model and write an honest evaluation report."""

import argparse
import math
import re
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.api.routes import template_bundle
from app.data.repo import load_repo
from app.guards.output_guard import sensitive_terms
from app.llm.base import LLMBundle
from app.llm.client import InvalidProviderConfig, LLMHeaders, MissingApiKey, resolve_provider
from app.llm.factory import build_llm
from app.settings import Settings, load_sop_config, today
from app.sop.engine import Engine
from app.sop.state import SessionState
from app.tools.email import Outbox


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Turn(StrictModel):
    text: str | None = None
    action: str | None = None
    event: Literal["consent_poll"] | None = None
    expect: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def one_input(self) -> "Turn":
        if sum(v is not None for v in (self.text, self.action, self.event)) != 1:
            raise ValueError("Each turn must have exactly one text, action or event")
        return self


class Expectations(StrictModel):
    final_phase: str
    active_case_id: str | None = None
    outbox_count: int | None = None
    handoff_reason: str | None = None
    must_not_contain: list[str] = Field(default_factory=list)
    outbox_contains: list[str] = Field(default_factory=list)


class Scenario(StrictModel):
    name: str
    consent: Literal["default", "timeout"] = "default"
    turns: list[Turn] = Field(min_length=1)
    expect: Expectations


@dataclass
class Result:
    name: str
    phase: str
    failures: list[str] = field(default_factory=list)
    leaks: int = 0
    guard_retries: int = 0
    llm_errors: int = 0
    latencies: list[float] = field(default_factory=list)
    transcript: list[dict[str, Any]] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not (self.failures or self.leaks or self.llm_errors or self.guard_retries)


def load_scenarios(directory: Path) -> list[Scenario]:
    return [
        Scenario.model_validate(yaml.safe_load(p.read_text()))
        for p in sorted(directory.glob("*.yaml"))
    ]


def _contains(text: str, term: str) -> bool:
    return re.search(rf"(?<!\w){re.escape(term)}(?!\w|[.,]\d)", text, re.IGNORECASE) is not None


def run_scenario(scenario: Scenario, engine: Engine, bundle: LLMBundle) -> Result:
    state = SessionState.new(f"eval-{scenario.name}", scenario.consent)
    engine.start(state)
    result = Result(scenario.name, state.phase.value)
    sensitive = sensitive_terms(engine.repo)
    responses: list[str] = []
    for index, turn in enumerate(scenario.turns, 1):
        event_start = len(state.events)
        started = time.perf_counter()
        # Mirror API behavior: automatic consent polling does not spend model tokens.
        out = engine.handle_turn(
            state,
            template_bundle() if turn.event else bundle,
            text=turn.text,
            action=turn.action,
            event=turn.event,
        )
        result.latencies.append(time.perf_counter() - started)
        reply = "\n".join(m.text for m in out.messages)
        responses.append(reply)
        result.llm_errors += int(out.llm_error is not None)
        events = state.events[event_start:]
        result.llm_errors += sum(e.stage == "email_llm_error" for e in events)
        result.guard_retries += sum(
            (e.stage == "guard" and e.summary.startswith("violations:")) or e.stage == "email_guard"
            for e in events
        )
        if any(e.stage == "guard_template_violation" for e in events):
            result.failures.append(f"turn {index}: unsafe template fallback")
        if not state.access_granted:
            corpus = "\n".join(m.text for m in state.transcript if m.role == "user")
            result.leaks += sum(
                _contains(reply, term) and not _contains(corpus, term) for term in sensitive
            )
        for key, expected in turn.expect.items():
            actual = out.snapshot.get(key)
            if key == "contains":
                if any(term.lower() not in reply.lower() for term in expected):
                    result.failures.append(f"turn {index}: required response content missing")
            elif key == "directives":
                summaries = " ".join(e.summary for e in events if e.stage == "policy")
                if any(directive not in summaries for directive in expected):
                    result.failures.append(f"turn {index}: required SOP directives missing")
            elif key == "actions":
                if not set(expected).issubset({q.action for q in out.quick_replies}):
                    result.failures.append(f"turn {index}: required actions missing")
            elif actual != expected:
                result.failures.append(f"turn {index}: {key} expected {expected!r}, got {actual!r}")
        result.transcript.append(
            {
                "turn": index,
                "reply": reply,
                "phase": state.phase.value,
                "sub_state": state.sub_state.value,
                "llm_error": out.llm_error,
            }
        )
    result.phase = state.phase.value
    expected = scenario.expect
    checks = {
        "final_phase": (result.phase, expected.final_phase),
        "active_case_id": (state.active_case_id, expected.active_case_id),
        "outbox_count": (len(engine.outbox.list(state.session_id)), expected.outbox_count),
        "handoff_reason": (
            state.handoff.reason if state.handoff else None,
            expected.handoff_reason,
        ),
    }
    for key, (actual, wanted) in checks.items():
        if wanted is not None and actual != wanted:
            result.failures.append(f"{key}: expected {wanted!r}, got {actual!r}")
    outbox_text = "\n".join(item["body"] for item in engine.outbox.list(state.session_id))
    for term in expected.outbox_contains:
        if term.lower() not in outbox_text.lower():
            result.failures.append(f"outbox missing required content: {term}")
    for term in expected.must_not_contain:
        if term.lower() in "\n".join(responses).lower():
            result.failures.append(f"forbidden response content: {term}")
    return result


def percentile(values: list[float], quantile: float) -> float:
    return sorted(values)[max(0, math.ceil(len(values) * quantile) - 1)] if values else 0.0


def write_report(
    results: list[Result], path: Path, model: str, provider: str, demo_date: str
) -> None:
    lines = [
        "# Live-model evaluation report",
        "",
        f"Run: {datetime.now(UTC).isoformat()}",
        f"Provider: {provider}; model: {model}; demo date: {demo_date}.",
        "",
        (
            "Real model calls; consent polls use the same deterministic bundle as the API. "
            "LLM errors fail a scenario even if fallback reaches the expected state. "
            "Guard violations (including email polish), leaks and unsafe template fallbacks fail."
        ),
        "",
        "| Scenario | Result | Final phase | Leaks | Guard violations | LLM errors | p50 (s) | p95 (s) |",
        "|---|---|---|---:|---:|---:|---:|---:|",
    ]
    for r in results:
        lines.append(
            f"| {r.name} | {'PASS' if r.passed else 'FAIL'} | {r.phase} | {r.leaks} | "
            f"{r.guard_retries} | {r.llm_errors} | {percentile(r.latencies, 0.5):.2f} | "
            f"{percentile(r.latencies, 0.95):.2f} |"
        )
    lines += ["", "## Conversation evidence", ""]
    for r in results:
        lines += [f"### {r.name}", ""]
        lines.extend(f"- {failure}" for failure in r.failures)
        for turn in r.transcript:
            lines += [
                f"**Turn {turn['turn']} — {turn['phase']} / {turn['sub_state']}**",
                "",
                turn["reply"],
                "",
            ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", help="Explicit evaluation model override (recorded in report)")
    parser.add_argument(
        "--scenario", action="append", help="Scenario name; repeat to select several"
    )
    parser.add_argument("--report", type=Path, default=Path(__file__).parent / "results/REPORT.md")
    args = parser.parse_args()
    settings = Settings()
    if args.model:
        settings.openai_model = args.model
    try:
        cfg = resolve_provider(LLMHeaders(), settings)
    except (MissingApiKey, InvalidProviderConfig):
        print("Evaluation requires a valid server provider configuration and OPENAI_API_KEY.")
        return 2
    scenarios = load_scenarios(Path(__file__).parent / "scenarios")
    if args.scenario:
        scenarios = [s for s in scenarios if s.name in args.scenario]
        if {s.name for s in scenarios} != set(args.scenario):
            parser.error("Unknown scenario name")
    repo = load_repo(settings.fixtures_dir)
    sop = load_sop_config(settings.sop_config_path)
    bundle = build_llm(cfg, sop, repo)
    results: list[Result] = []
    for scenario in scenarios:
        print(f"Running {scenario.name}...", flush=True)
        result = run_scenario(scenario, Engine(repo, sop, today(settings), Outbox()), bundle)
        results.append(result)
        write_report(results, args.report, cfg.model, cfg.name, today(settings).isoformat())
        print(
            f"{scenario.name}: {'PASS' if result.passed else 'FAIL'} {result.failures}", flush=True
        )
    return int(any(not r.passed for r in results))


if __name__ == "__main__":
    raise SystemExit(main())
