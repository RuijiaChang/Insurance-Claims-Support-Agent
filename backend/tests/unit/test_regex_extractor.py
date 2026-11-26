from datetime import date

from app.llm.regex_extractor import extract_regex
from app.tools.identity import parse_dob

MARGARET = (
    "I'm the policyholder. My name is Margaret Chen, policy POL-9921. "
    "I'm calling about my denied healthcare claim from January. "
    "DOB is 1985-03-15, SSN last four is 4472."
)


def test_margaret_opener() -> None:
    hits = extract_regex(MARGARET)
    assert hits.dob_raw is not None
    assert parse_dob(hits.dob_raw) == [date(1985, 3, 15)]
    assert hits.id_last4 == "4472"
    assert hits.policy_number == "POL-9921"
    assert hits.phone is None


def test_last4_needs_keyword_and_skips_years() -> None:
    assert extract_regex("my ssn last 4 is 4472 and I was born in 1985").id_last4 == "4472"
    assert extract_regex("I was born in 1985").id_last4 is None


def test_last4_not_from_ids() -> None:
    hits = extract_regex("policy POL-9921, claim CL-2048")
    assert hits.id_last4 is None
    assert hits.case_id == "CL-2048"


def test_phone_and_email() -> None:
    hits = extract_regex("reach me at (650) 521-2836 or Margaret@Email.com")
    assert hits.phone == "+16505212836"
    assert hits.email == "margaret@email.com"


def test_dob_natural_language() -> None:
    hits = extract_regex("born March 15, 1985")
    assert hits.dob_raw is not None
    assert "March 15, 1985" in hits.dob_raw


def test_national_id_keyword() -> None:
    assert extract_regex("national id last four digits 6688").id_last4 == "6688"


def test_dob_other_formats() -> None:
    assert extract_regex("dob 3/15/85").dob_raw == "3/15/85"
    assert extract_regex("born 15 March 1985").dob_raw == "15 March 1985"


def test_phone_formats() -> None:
    for s in ("650.521.2836", "+1 650 521 2836", "6505212836"):
        assert extract_regex(f"call {s}").phone == "+16505212836"


def test_nothing_found() -> None:
    hits = extract_regex("hello there")
    assert hits == extract_regex("")
    assert hits.dob_raw is None and hits.phone is None and hits.email is None
