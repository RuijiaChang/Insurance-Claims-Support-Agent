"""Prompt files (markdown) for the LLM implementations."""

from functools import cache
from pathlib import Path

_DIR = Path(__file__).resolve().parent


@cache
def load_prompt(name: str) -> str:
    """The prompt file ``<name>.md`` from this package, stripped."""
    return (_DIR / f"{name}.md").read_text(encoding="utf-8").strip()
