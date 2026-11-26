"""Build the real LLM bundle: one shared client behind extractor, responder and composer."""

from typing import Any

from app.data.repo import FixtureRepo
from app.llm.base import LLMBundle
from app.llm.client import LLMClient, ProviderConfig
from app.llm.email_composer import LLMEmailComposer
from app.llm.extractor import LLMExtractor
from app.llm.responder import LLMResponder
from app.settings import SopConfig


def build_llm(
    cfg: ProviderConfig, sop: SopConfig, repo: FixtureRepo, *, http_client: Any = None
) -> LLMBundle:
    client = LLMClient(cfg, http_client=http_client)
    return LLMBundle(
        extractor=LLMExtractor(client),
        responder=LLMResponder(client, sop.process.max_tool_iterations),
        email_composer=LLMEmailComposer(client, repo),
    )
