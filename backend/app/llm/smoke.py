"""Live smoke test: one real turn with Margaret's opener.

Usage: ``OPENAI_API_KEY=... uv run python -m app.llm.smoke``. Exits non-zero without a key.
"""

import sys

from app.data.repo import load_repo
from app.llm.client import LLMHeaders, MissingApiKey, resolve_provider
from app.llm.factory import build_llm
from app.settings import Settings, load_sop_config, today
from app.sop.engine import Engine
from app.sop.state import SessionState
from app.tools.email import Outbox

OPENER = (
    "I'm the policyholder. My name is Margaret Chen, policy POL-9921. I'm calling about my "
    "denied healthcare claim from January. DOB is 1985-03-15, SSN last four is 4472."
)


def main() -> int:
    settings = Settings()
    try:
        cfg = resolve_provider(LLMHeaders(), settings)
    except MissingApiKey:
        print("OPENAI_API_KEY is not set.", file=sys.stderr)
        return 1
    repo = load_repo(settings.fixtures_dir)
    sop = load_sop_config(settings.sop_config_path)
    engine = Engine(repo, sop, today(settings), Outbox(settings.outbox_dir))
    state = SessionState.new("smoke")
    print(f"agent: {engine.start(state).messages[0].text}\n")
    print(f"caller: {OPENER}\n")
    result = engine.handle_turn(state, build_llm(cfg, sop, repo), text=OPENER)
    for message in result.messages:
        print(f"agent: {message.text}\n")
    print(f"phase: {state.phase.value}")
    if result.llm_error:
        print(f"llm_error: {result.llm_error}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
