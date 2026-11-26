"""Email summary models."""

from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING

from pydantic import BaseModel

if TYPE_CHECKING:
    from app.data.repo import FixtureRepo
    from app.sop.state import SessionState


class EmailDraft(BaseModel):
    subject: str
    to_masked: str
    sections: dict[str, list[str]]

    @property
    def body(self) -> str:
        """Plain-text body. A line starting with two spaces is a sub-item of the one above."""
        blocks = [
            title + "\n" + "\n".join(_bullet(line) for line in lines)
            for title, lines in self.sections.items()
        ]
        return "\n\n".join(blocks)


def _bullet(line: str) -> str:
    return f"    - {line.strip()}" if line.startswith("  ") else f"- {line}"


def _money(raw: str) -> str:
    try:
        return f"${Decimal(raw):,.2f}"
    except InvalidOperation:
        return raw


def _grouped(entries: list[tuple[str, str]], headers: dict[str, str]) -> list[str]:
    """One header line per claim, its items indented below it (no repeated claim id)."""
    lines: list[str] = []
    for cid in dict.fromkeys(cid for cid, _ in entries):
        lines.append(headers.get(cid, cid))
        lines.extend(f"  {text}" for c, text in entries if c == cid)
    return lines


_REACH_US = "Reply to this email or call the number on your insurance card to reach claims support."


def build_email_draft(state: "SessionState", repo: "FixtureRepo") -> EmailDraft:
    """Deterministic structured summary built only from ``case_log`` and claim records."""
    # Local imports: app.tools.* import this module at load time.
    from app.tools.claims import claim_summary_line
    from app.tools.email import mask_email

    if not state.access_granted or state.verified_party_id is None:
        raise ValueError("cannot build an email summary before access is granted")
    holder = repo.holder(state.verified_party_id)
    claims = {c.case_id: c for c in repo.claims_for(state.verified_party_id)}

    discussed_claims = [claims[cid] for cid in state.discussed_case_ids if cid in claims]
    headers = {c.case_id: f"{c.case_id} — {claim_summary_line(c)}" for c in discussed_claims}
    discussed = [headers[c.case_id] for c in discussed_claims] or [
        "General questions about your policy and claims."
    ]
    facts = [(e.case_id, e.text) for e in state.case_log if e.kind == "fact"]
    # The amounts on file for each claim discussed: callers ask about them in chat.
    for c in discussed_claims:
        facts.append(
            (c.case_id, f"Expected reimbursement: {_money(c.expected_reimbursement_amount)}")
        )
        facts.append((c.case_id, f"Allowed maximum: {_money(c.allowed_max_amount)}"))
        facts.append((c.case_id, f"Amount paid: {_money(c.net_pay)}"))
    steps = _grouped(
        [(e.case_id, e.text) for e in state.case_log if e.kind in ("next_step", "deadline")],
        headers,
    ) or ["No further action is needed right now."]
    return EmailDraft(
        subject="Summary of your claims support conversation",
        to_masked=mask_email(holder.email),
        sections={
            "What we discussed": discussed,
            "Claim status / outcome": _grouped(facts, headers),
            "Next steps": steps,
            "How to reach us": [_REACH_US],
        },
    )
