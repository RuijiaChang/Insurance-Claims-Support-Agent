from datetime import date

from app.data.repo import FixtureRepo, Policyholder
from app.tools.identity import (
    IDENTITY_FIELDS,
    IdentityField,
    field_matches,
    find_candidates,
    match_representative,
    normalize_phone,
    normalize_relationship,
    parse_dob,
    verify,
)

T = 90


def h(repo: FixtureRepo, pid: str) -> Policyholder:
    return repo.holder(pid)


def test_fields_order() -> None:
    assert IDENTITY_FIELDS == ("full_name", "dob", "phone", "email", "id_last4")


def test_parse_dob_formats() -> None:
    for s in ["1985-03-15", "March 15, 1985", "15 March 1985", "03/15/1985", "3/15/85"]:
        assert date(1985, 3, 15) in parse_dob(s)
    assert set(parse_dob("10/09/1964")) == {date(1964, 10, 9), date(1964, 9, 10)}
    assert parse_dob("not a date") == []


def test_normalize_phone_formats() -> None:
    for s in ["(650) 521-2836", "650.521.2836", "+1 650 521 2836", "6505212836"]:
        assert normalize_phone(s) == "+16505212836"
    assert normalize_phone("12345") is None


def test_name_matching(repo: FixtureRepo) -> None:
    assert field_matches("full_name", ["Yaven Li"], h(repo, "P13"), T)
    assert field_matches("full_name", ["margaret  chen"], h(repo, "P9"), T)
    assert field_matches("full_name", ["Margret Chen"], h(repo, "P9"), T)
    assert not field_matches("full_name", ["Ava Chen"], h(repo, "P9"), T)


def test_email_alias_case_insensitive(repo: FixtureRepo) -> None:
    assert field_matches("email", ["YAWEN.LI@example.com"], h(repo, "P13"), T)


def test_last4_any_id_type(repo: FixtureRepo) -> None:
    assert field_matches("id_last4", ["6688"], h(repo, "P12"), T)


def good() -> dict[IdentityField, list[str]]:
    return {"full_name": ["Margaret Chen"], "dob": ["1985-03-15"], "id_last4": ["4472"]}


def test_verify_insufficient(repo: FixtureRepo) -> None:
    out = verify(
        {"full_name": ["Margaret Chen"], "dob": ["1985-03-15"]},
        set(),
        None,
        repo.policyholders,
        T,
        3,
    )
    assert out.status == "insufficient"
    assert out.party_id is None


def test_verify_pass_margaret(repo: FixtureRepo) -> None:
    out = verify(good(), set(), None, repo.policyholders, T, 3)
    assert out.status == "pass"
    assert out.party_id == "P9"
    assert out.matched_fields == {"full_name", "dob", "id_last4"}


def test_verify_three_plus_one_mismatch_fails(repo: FixtureRepo) -> None:
    v = good()
    v["phone"] = ["+16500000000"]
    out = verify(v, set(), None, repo.policyholders, T, 3)
    assert out.status == "fail"


def test_verify_multiple_values_any_matches(repo: FixtureRepo) -> None:
    v = good()
    v["dob"] = ["1985-03-16", "1985-03-15"]
    assert verify(v, set(), None, repo.policyholders, T, 3).status == "pass"


def test_verify_unknown_person_fails(repo: FixtureRepo) -> None:
    v: dict[IdentityField, list[str]] = {
        "full_name": ["Zed Zzyzx"],
        "dob": ["1900-01-01"],
        "id_last4": ["0000"],
    }
    out = verify(v, set(), None, repo.policyholders, T, 3)
    assert out.status == "fail"
    assert out.party_id is None


def test_refused_not_counted(repo: FixtureRepo) -> None:
    v: dict[IdentityField, list[str]] = {
        "full_name": ["Margaret Chen"],
        "dob": ["1985-03-15"],
        "phone": ["6505212836"],
    }
    out = verify(v, {"phone"}, None, repo.policyholders, T, 3)
    assert out.status == "insufficient"


def test_policy_number_locates_first(repo: FixtureRepo) -> None:
    c = find_candidates(good(), "POL-9921", repo.policyholders, T)
    assert [p.party_id for p in c] == ["P9"]


def test_match_representative(repo: FixtureRepo) -> None:
    reps = repo.representatives
    assert match_representative("David Chen", "child", "P9", reps, T)
    assert not match_representative("David Chen", "parent", "P9", reps, T)
    assert not match_representative("John Doe", "child", "P9", reps, T)


def test_normalize_relationship() -> None:
    for s in ["son", "daughter", "child"]:
        assert normalize_relationship(s) == "child"
    for s in ["mom", "mother", "dad", "parent"]:
        assert normalize_relationship(s) == "parent"
    for s in ["wife", "husband"]:
        assert normalize_relationship(s) == "spouse"
