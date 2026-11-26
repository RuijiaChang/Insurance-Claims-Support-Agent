import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from pydantic import BaseModel


class Policyholder(BaseModel):
    party_id: str
    name: str
    policy_number: str
    dob: date
    id_type: str
    id_last4: str
    phone: str
    email: str
    name_aliases: list[str] = []
    phone_aliases: list[str] = []
    email_aliases: list[str] = []


class Claim(BaseModel):
    case_id: str
    party_id: str
    case_type: str
    created_at: date
    status: str
    summary: str
    denial_reason: str | None = None
    documents_needed: list[str] = []
    appeal_deadline: date | None = None
    expected_reimbursement_amount: str
    allowed_max_amount: str
    net_pay: str
    net_fee: str


class Representative(BaseModel):
    rep_name: str
    relationship: str
    buyer_name: str
    buyer_party_id: str


@dataclass
class FixtureRepo:
    policyholders: list[Policyholder]
    claims: list[Claim]
    representatives: list[Representative]
    consent_scenarios: dict[str, list[str]]
    guideline: dict[str, Any]
    claim_schema: dict[str, Any]

    def claims_for(self, party_id: str) -> list[Claim]:
        return [c for c in self.claims if c.party_id == party_id]

    def holder(self, party_id: str) -> Policyholder:
        for h in self.policyholders:
            if h.party_id == party_id:
                return h
        raise KeyError(party_id)


def _read(fixtures_dir: Path, name: str) -> Any:
    with (fixtures_dir / name).open(encoding="utf-8") as f:
        return json.load(f)


def load_repo(fixtures_dir: Path) -> FixtureRepo:
    scenarios = _read(fixtures_dir, "consent_scenarios.json")
    return FixtureRepo(
        policyholders=[
            Policyholder.model_validate(x) for x in _read(fixtures_dir, "policyholders.json")
        ],
        claims=[Claim.model_validate(x) for x in _read(fixtures_dir, "claims.json")],
        representatives=[
            Representative.model_validate(x) for x in _read(fixtures_dir, "representatives.json")
        ],
        consent_scenarios={k: list(v["status_sequence"]) for k, v in scenarios.items()},
        guideline=_read(fixtures_dir, "required_document_guideline.json"),
        claim_schema=_read(fixtures_dir, "claim_schema.json"),
    )
