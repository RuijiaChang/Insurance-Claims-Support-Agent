"""LLMExtractor: one structured-output call per user message."""

import json

from app.llm.base import ExtractContext
from app.llm.client import LLMClient
from app.llm.prompts import load_prompt
from app.sop.extraction import Extraction


class LLMExtractor:
    def __init__(self, client: LLMClient) -> None:
        self.client = client

    def _system(self) -> str:
        system = load_prompt("extract")
        if not self.client.config.supports_structured:
            # JSON mode has no schema of its own: spell it out for the model.
            schema = json.dumps(Extraction.model_json_schema())
            system += f"\n\n# JSON schema of the output object\n\n{schema}"
        return system

    def extract(self, text: str, ectx: ExtractContext) -> Extraction:
        pending = ectx.pending_question
        payload = {
            "phase": ectx.phase.value,
            "pending_question": pending.model_dump(mode="json") if pending is not None else None,
            "last_agent_message": ectx.last_agent_message,
            "user_message": text,
        }
        messages = [
            {"role": "system", "content": self._system()},
            {"role": "user", "content": json.dumps(payload)},
        ]
        return self.client.parse(messages, Extraction)
