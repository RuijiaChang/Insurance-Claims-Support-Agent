"""Email summary models."""

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
        blocks = [
            title + "\n" + "\n".join(f"- {line}" for line in lines)
            for title, lines in self.sections.items()
        ]
        return "\n\n".join(blocks)


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

    discussed = [
        f"{cid}: {claim_summary_line(claims[cid])}"
        for cid in state.discussed_case_ids
        if cid in claims
    ] or ["General questions about your policy and claims."]
    facts = [f"{e.case_id}: {e.text}" for e in state.case_log if e.kind == "fact"]
    steps = [
        f"{e.case_id}: {e.text}" for e in state.case_log if e.kind in ("next_step", "deadline")
    ] or ["No further action is needed right now."]
    return EmailDraft(
        subject="Summary of your claims support conversation",
        to_masked=mask_email(holder.email),
        sections={
            "What we discussed": discussed,
            "Claim status / outcome": facts,
            "Next steps": steps,
            "How to reach us": [_REACH_US],
        },
    )
