"""Mock outbox (acts as the mail server) and PII masking helpers."""

import secrets
from datetime import UTC, datetime
from email.message import EmailMessage
from pathlib import Path

from app.sop.email_summary import EmailDraft

SENDER = "claims-support@example.com"


def mask_email(e: str) -> str:
    local, _, domain = e.partition("@")
    return f"{local[:1]}*****@{domain}"


def mask_phone(p: str) -> str:
    return f"***-***-**{p[-2:]}"


class Outbox:
    def __init__(self, outbox_dir: Path | None = None) -> None:
        self._dir = outbox_dir
        self._items: dict[str, list[dict[str, str]]] = {}

    def send(self, session_id: str, to: str, draft: EmailDraft) -> str:
        message_id = "MSG-" + secrets.token_hex(4)
        item = {
            "message_id": message_id,
            "to": to,
            "to_masked": mask_email(to),
            "sent_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "subject": draft.subject,
            "body": draft.body,
        }
        self._items.setdefault(session_id, []).append(item)
        if self._dir is not None:
            msg = EmailMessage()
            msg["From"] = SENDER
            msg["To"] = to
            msg["Subject"] = draft.subject
            msg["Message-ID"] = f"<{message_id}@example.com>"
            msg.set_content(draft.body)
            self._dir.mkdir(parents=True, exist_ok=True)
            (self._dir / f"{session_id}-{message_id}.eml").write_bytes(bytes(msg))
        return message_id

    def list(self, session_id: str) -> list[dict[str, str]]:
        return list(self._items.get(session_id, []))
