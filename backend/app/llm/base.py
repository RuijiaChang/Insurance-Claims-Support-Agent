"""LLM-facing protocols: what the engine needs from an extractor, a responder and a composer.

Concrete providers (and the test fakes) implement these; the engine never imports a
provider SDK directly, so every LLM failure reaches it as an ``LLMError``.
"""

from dataclasses import dataclass
from typing import Literal, Protocol

from app.sop.context import ResponderContext
from app.sop.extraction import Extraction
from app.sop.phases import Phase
from app.sop.plan import EmailComposer
from app.sop.state import PendingQuestion

LLMErrorKind = Literal["auth", "rate_limit", "timeout", "other"]


class LLMError(Exception):
    def __init__(self, kind: LLMErrorKind, message: str = "") -> None:
        super().__init__(message or kind)
        self.kind: LLMErrorKind = kind
        self.message = message


@dataclass(frozen=True)
class ExtractContext:
    phase: Phase
    pending_question: PendingQuestion | None
    last_agent_message: str | None


class Extractor(Protocol):
    def extract(self, text: str, ectx: ExtractContext) -> Extraction: ...


class Responder(Protocol):
    def respond(self, rctx: ResponderContext, feedback: list[str] | None = None) -> str: ...


@dataclass
class LLMBundle:
    extractor: Extractor
    responder: Responder
    email_composer: EmailComposer
