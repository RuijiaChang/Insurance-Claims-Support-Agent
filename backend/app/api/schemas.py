"""Request and response bodies for the REST API (spec §12; no ``suggestions``)."""

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

# Mirrors sop.yaml session.max_text_len (a test keeps them equal).
MAX_TEXT_LEN = 4000
ConsentScenario = Literal["default", "timeout"]
CONSENT_SCENARIOS: list[str] = ["default", "timeout"]


class SessionIn(BaseModel):
    consent_scenario: ConsentScenario = "default"


class MessageIn(BaseModel):
    text: str | None = None
    action: str | None = Field(default=None, min_length=1, max_length=64)

    @model_validator(mode="after")
    def _check(self) -> "MessageIn":
        if self.text is not None:
            stripped = self.text.strip()
            if not stripped:
                raise ValueError("text must not be blank")
            if len(stripped) > MAX_TEXT_LEN:
                raise ValueError(f"text must be at most {MAX_TEXT_LEN} characters")
            self.text = stripped
        if self.text is None and self.action is None:
            raise ValueError("either text or action is required")
        return self


class EventIn(BaseModel):
    type: Literal["consent_poll"]


class MessageOut(BaseModel):
    role: str
    text: str


class QuickReplyOut(BaseModel):
    label: str
    action: str


class TurnOut(BaseModel):
    messages: list[MessageOut]
    state: dict[str, Any]
    quick_replies: list[QuickReplyOut]
    llm_error: str | None = None


class SessionOut(BaseModel):
    session_id: str
    messages: list[MessageOut]
    state: dict[str, Any]
    quick_replies: list[QuickReplyOut]


class ConfigOut(BaseModel):
    has_server_key: bool
    provider: str | None
    model: str | None
    demo_today: str
    consent_scenarios: list[str]


class ValidateKeyIn(BaseModel):
    provider: str = "openai"
    base_url: str | None = None
    model: str | None = None
    api_key: str = Field(min_length=1, repr=False)


class ValidateKeyOut(BaseModel):
    ok: bool
    error: str | None = None
