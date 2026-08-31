"""9B tests: GET /loans, GET /summary, GET /audit/{loan_id}.

These are the three Module H endpoints that were missing, and they back all three role
dashboards. Counts are asserted against deliberately seeded state rather than against
themselves, so a wrong aggregate fails rather than agreeing with its own bug.
"""

import pytest
import tests.test_verification_6a as base
from fastapi.testclient import TestClient

from app.core.seed import hash_password
from app.main import app
from app.models.exception import ExceptionRecord
from app.models.user import User
from app.validators.engine import clear_rules, validate_loan
from app.validators.rules import register_default_rules

client = TestClient(app)


@pytest.fixture(scope="session", autouse=True)
def schema():
    base.create_db_and_tables()
    yield


@pytest.fixture(autouse=True)
def clean():
    clear_rules()
    base._clear_database()
    register_default_rules()
    try:
        yield
    finally:
        clear_rules()
        base._clear_database()


def _authenticate(username: str, role: str) -> dict[str, str]:
    with base.SessionLocal() as db:
        if db.query(User).filter(User.username == username).one_or_none() is None:
            db.add(User(username=username, password_hash=hash_password("dev_password"), role=role))
            db.commit()
    response = client.post("/auth/login", json={"username": username, "password": "dev_password"})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _seed_failing_loan(loan_id: str) -> str:
    """A loan whose only failure is balance_gt_principal.

    borrower_id is unique per loan: base._seed_loan reuses one borrower, and several
    loans sharing a borrower/principal/origination date would additionally trip
    duplicate_borrower_amount_date and muddy the counts being asserted.
    """
    base._seed_loan(
        loan_id=loan_id,
        borrower_id=f"B-{loan_id}",
        current_balance=300000.0,
        original_principal=250000.0,
    )
    validate_loan(loan_id)
    return loan_id


def _seed_clean_loan(loan_id: str) -> str:
    """A loan that passes every rule."""
    base._seed_loan(loan_id=loan_id, borrower_id=f"B-{loan_id}")
    validate_loan(loan_id)
    return loan_id


# ---------------------------------------------------------------------------
# GET /loans
# ---------------------------------------------------------------------------


def test_loans_list_returns_review_state_per_loan():
    failing = _seed_failing_loan("L-9B-BAD")
    clean = _seed_clean_loan("L-9B-CLEAN")
    headers = _authenticate("op-9b-list", "data_operator")

    body = client.get("/loans", headers=headers).json()
    by_id = {item["loan_id"]: item for item in body["items"]}

    assert body["total"] == 2
    assert by_id[failing]["open_exception_count"] >= 1
    assert by_id[clean]["open_exception_count"] == 0
    assert by_id[failing]["verified"] is False
    assert by_id[failing]["current_balance"] == 300000.0


def test_loans_list_filters_by_open_exceptions():
    failing = _seed_failing_loan("L-9B-BAD2")
    _seed_clean_loan("L-9B-CLEAN2")
    headers = _authenticate("op-9b-filter", "data_operator")

    with_open = client.get("/loans", params={"has_open_exceptions": True}, headers=headers).json()
    assert [item["loan_id"] for item in with_open["items"]] == [failing]

    without_open = client.get("/loans", params={"has_open_exceptions": False}, headers=headers).json()
    assert failing not in [item["loan_id"] for item in without_open["items"]]


def test_loans_list_searches_by_loan_and_borrower_id():
    _seed_clean_loan("L-9B-SEARCH")
    headers = _authenticate("op-9b-search", "data_operator")

    assert client.get("/loans", params={"search": "9B-SEARCH"}, headers=headers).json()["total"] == 1
    assert client.get("/loans", params={"search": "no-such-loan"}, headers=headers).json()["total"] == 0


def test_loans_list_paginates_deterministically():
    for index in range(5):
        _seed_clean_loan(f"L-9B-PAGE-{index}")
    headers = _authenticate("op-9b-page", "data_operator")

    first = client.get("/loans", params={"page": 1, "page_size": 2}, headers=headers).json()
    second = client.get("/loans", params={"page": 2, "page_size": 2}, headers=headers).json()

    assert first["total"] == 5 and first["total_pages"] == 3
    assert len(first["items"]) == 2
    assert {i["loan_id"] for i in first["items"]}.isdisjoint({i["loan_id"] for i in second["items"]})
    # stable ordering -> repeating the request returns the same page
    assert client.get("/loans", params={"page": 1, "page_size": 2}, headers=headers).json() == first


def test_loans_list_requires_authentication():
    assert client.get("/loans").status_code == 401


# ---------------------------------------------------------------------------
# GET /summary
# ---------------------------------------------------------------------------


def test_summary_counts_match_seeded_state():
    _seed_failing_loan("L-9B-SUM-BAD")
    _seed_clean_loan("L-9B-SUM-CLEAN")
    headers = _authenticate("reviewer-9b-sum", "reviewer")

    body = client.get("/summary", headers=headers).json()

    assert body["loans"]["total"] == 2
    assert body["loans"]["with_open_exceptions"] == 1
    assert body["loans"]["clean"] == 1
    assert body["loans"]["verified"] == 0

    assert body["exceptions"]["total"] >= 1
    assert body["exceptions"]["open"] >= 1
    assert sum(body["exceptions"]["by_severity"].values()) == body["exceptions"]["total"]
    assert sum(item["count"] for item in body["exceptions"]["by_type"]) == body["exceptions"]["total"]

    assert body["validation"]["total_results"] == body["validation"]["passed"] + body["validation"]["failed"]
    assert body["validation"]["failed"] >= 1
    assert body["ai"]["recommendations"] == 0
    assert body["verification"]["verified_records"] == 0


def test_summary_data_quality_score_reflects_clean_loan_share():
    _seed_failing_loan("L-9B-DQ-BAD")
    _seed_clean_loan("L-9B-DQ-1")
    _seed_clean_loan("L-9B-DQ-2")
    _seed_clean_loan("L-9B-DQ-3")
    headers = _authenticate("consumer-9b-dq", "data_consumer")

    # 3 of 4 loans carry no unresolved exception
    assert client.get("/summary", headers=headers).json()["data_quality_score"] == 0.75


def test_summary_is_empty_but_valid_on_a_clean_database():
    headers = _authenticate("reviewer-9b-empty", "reviewer")
    body = client.get("/summary", headers=headers).json()

    assert body["loans"]["total"] == 0
    assert body["exceptions"]["total"] == 0
    assert body["exceptions"]["by_type"] == []
    assert body["data_quality_score"] == 0.0, "an empty portfolio must not report a perfect score"


def test_summary_tracks_verification_and_export():
    loan_id = _seed_clean_loan("L-9B-VERIFY")
    headers = _authenticate("reviewer-9b-verify", "reviewer")

    verified = client.post("/verified-loans", json={"loan_id": loan_id}, headers=headers).json()
    assert verified["status"] == "verified"
    body = client.get("/summary", headers=headers).json()
    assert body["loans"]["verified"] == 1
    assert body["verification"]["verified_records"] == 1
    assert body["verification"]["exported"] == 0

    client.post(f"/verified-loans/{verified['verified_record_id']}/export", headers=headers)
    assert client.get("/summary", headers=headers).json()["verification"]["exported"] == 1


def test_summary_requires_authentication():
    assert client.get("/summary").status_code == 401


# ---------------------------------------------------------------------------
# GET /audit/{loan_id}
# ---------------------------------------------------------------------------


def test_audit_trail_returns_events_for_the_loan_oldest_first():
    loan_id = _seed_failing_loan("L-9B-AUDIT")
    headers = _authenticate("consumer-9b-audit", "data_consumer")

    body = client.get(f"/audit/{loan_id}", headers=headers).json()

    assert body["loan_id"] == loan_id
    assert body["total"] >= 2
    event_types = [item["event_type"] for item in body["items"]]
    assert "validation_executed" in event_types
    assert "exception_created" in event_types
    ids = [item["id"] for item in body["items"]]
    assert ids == sorted(ids), "events must be oldest-first and deterministic"
    assert all("actor" in item and "details" in item for item in body["items"])


def test_audit_trail_is_scoped_to_one_loan():
    first = _seed_failing_loan("L-9B-SCOPE-A")
    _seed_failing_loan("L-9B-SCOPE-B")
    headers = _authenticate("consumer-9b-scope", "data_consumer")

    with base.SessionLocal() as db:
        expected = db.query(ExceptionRecord).filter_by(loan_id=first).count()
    assert expected >= 1

    body = client.get(f"/audit/{first}", headers=headers).json()
    for item in body["items"]:
        if item["details"] and "loan_id" in item["details"]:
            assert item["details"]["loan_id"] == first


def test_audit_trail_paginates():
    loan_id = _seed_failing_loan("L-9B-AUDIT-PAGE")
    headers = _authenticate("consumer-9b-apage", "data_consumer")

    page = client.get(f"/audit/{loan_id}", params={"page": 1, "page_size": 1}, headers=headers).json()
    assert len(page["items"]) == 1
    assert page["total_pages"] == page["total"]


def test_audit_trail_unknown_loan_returns_404():
    headers = _authenticate("consumer-9b-404", "data_consumer")
    assert client.get("/audit/L-DOES-NOT-EXIST", headers=headers).status_code == 404


def test_audit_trail_requires_authentication():
    loan_id = _seed_clean_loan("L-9B-AUDIT-AUTH")
    assert client.get(f"/audit/{loan_id}").status_code == 401
