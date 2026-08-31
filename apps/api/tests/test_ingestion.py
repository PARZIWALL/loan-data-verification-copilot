import io
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_ingestion.db")

from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.database import Base, SessionLocal, engine
from app.core.seed import hash_password, seed_users
from app.main import app
from app.models.user import User


def reset_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    seed_users()


def _authenticate_data_operator(client: TestClient) -> dict[str, str]:
    username = "ingestion-data-operator"
    with SessionLocal() as db:
        user = db.query(User).filter(User.username == username).one_or_none()
        if user is None:
            db.add(User(username=username, password_hash=hash_password("dev_password"), role="data_operator"))
            db.commit()
    response = client.post("/auth/login", json={"username": username, "password": "dev_password"})
    assert response.status_code == 200, response.text
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_upload_requires_authentication():
    reset_db()
    csv_data = "loan_id,borrower_id,origination_date,original_principal,current_balance,term_months\nL-0001,B-000,2024-01-01,100000,95000,120\n"
    client = TestClient(app)
    response = client.post(
        "/upload",
        data={"source_type": "loan_tape"},
        files={"file": ("loan_tape.csv", csv_data, "text/csv")},
    )
    assert response.status_code == 401


def test_upload_rejects_non_data_operator_roles():
    reset_db()
    username = "ingestion-reviewer"
    with SessionLocal() as db:
        db.add(User(username=username, password_hash=hash_password("dev_password"), role="reviewer"))
        db.commit()
    client = TestClient(app)
    login = client.post("/auth/login", json={"username": username, "password": "dev_password"})
    assert login.status_code == 200
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    csv_data = "loan_id,borrower_id,origination_date,original_principal,current_balance,term_months\nL-0002,B-000,2024-01-01,100000,95000,120\n"
    response = client.post(
        "/upload",
        data={"source_type": "loan_tape"},
        files={"file": ("loan_tape.csv", csv_data, "text/csv")},
        headers=headers,
    )
    assert response.status_code == 403


def test_valid_loan_tape_row_imports_successfully():
    reset_db()
    csv_data = "loan_id,borrower_id,origination_date,original_principal,current_balance,term_months\nL-1001,B-001,2024-01-15,250000,240000,360\n"
    client = TestClient(app)
    headers = _authenticate_data_operator(client)
    response = client.post(
        "/upload",
        data={"source_type": "loan_tape"},
        files={"file": ("loan_tape.csv", csv_data, "text/csv")},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["source_type"] == "loan_tape"
    assert payload["total_rows"] == 1
    assert payload["imported_rows"] == 1
    assert payload["failed_rows"] == 0


def test_raw_row_and_primary_source_link_are_preserved():
    reset_db()
    csv_data = "loan_id,borrower_id,origination_date,original_principal,current_balance,term_months\nL-2002,B-002,2024-02-10,100000,98000,180\n"
    client = TestClient(app)
    headers = _authenticate_data_operator(client)
    response = client.post(
        "/upload",
        data={"source_type": "loan_tape"},
        files={"file": ("loan_tape.csv", csv_data, "text/csv")},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    with SessionLocal() as db:
        loan = db.execute(text("SELECT loan_id, primary_source_id FROM loans WHERE loan_id = 'L-2002'" )).fetchone()
        source = db.execute(text("SELECT id, source_file, source_row_number, import_status FROM loan_sources WHERE loan_id = 'L-2002' ORDER BY id DESC LIMIT 1")).fetchone()
        assert loan is not None
        assert source is not None
        assert loan[1] == source[0]
        assert source[1] == "loan_tape.csv"
        assert source[2] == 2


def test_malformed_row_is_reported_without_crashing_import():
    reset_db()
    csv_data = "loan_id,borrower_id,origination_date,original_principal,current_balance,term_months\nL-3001,B-003,2024-03-20,invalid,90000,180\n"
    client = TestClient(app)
    headers = _authenticate_data_operator(client)
    response = client.post(
        "/upload",
        data={"source_type": "loan_tape"},
        files={"file": ("loan_tape.csv", csv_data, "text/csv")},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["failed_rows"] == 1
    assert payload["failed_details"][0]["row_number"] == 2
    assert "reason" in payload["failed_details"][0]


def test_secondary_sources_do_not_overwrite_canonical_loans():
    reset_db()
    client = TestClient(app)
    headers = _authenticate_data_operator(client)
    initial = "loan_id,borrower_id,origination_date,original_principal,current_balance,term_months\nL-4001,B-004,2024-04-01,500000,480000,360\n"
    client.post("/upload", data={"source_type": "loan_tape"}, files={"file": ("loan_tape.csv", initial, "text/csv")}, headers=headers)

    secondary = "loan_id,borrower_id,origination_date,original_principal,current_balance,term_months\nL-4001,B-999,2024-04-05,999999,999999,999\n"
    response = client.post(
        "/upload",
        data={"source_type": "servicer_update"},
        files={"file": ("servicer_update.csv", secondary, "text/csv")},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["imported_rows"] == 1
    with SessionLocal() as db:
        loan = db.execute(text("SELECT borrower_id, current_balance, original_principal FROM loans WHERE loan_id = 'L-4001' ")).fetchone()
        assert loan[0] == "B-004"
        assert loan[1] == 480000.0
        assert loan[2] == 500000.0


def test_document_manifest_creates_raw_rows_only():
    reset_db()
    csv_data = "loan_id,document_type,doc_status\nL-5001,credit_file,received\n"
    client = TestClient(app)
    headers = _authenticate_data_operator(client)
    response = client.post(
        "/upload",
        data={"source_type": "document_manifest"},
        files={"file": ("document_manifest.csv", csv_data, "text/csv")},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    with SessionLocal() as db:
        src_count = db.execute(text("SELECT COUNT(*) FROM loan_sources WHERE source_file = 'document_manifest.csv' ")).scalar_one()
        loan_count = db.execute(text("SELECT COUNT(*) FROM loans WHERE loan_id = 'L-5001' ")).scalar_one()
        assert src_count == 1
        assert loan_count == 0


def test_reupload_does_not_duplicate_canonical_loans():
    reset_db()
    csv_data = "loan_id,borrower_id,origination_date,original_principal,current_balance,term_months\nL-6001,B-006,2024-06-01,200000,195000,240\n"
    client = TestClient(app)
    headers = _authenticate_data_operator(client)
    first = client.post("/upload", data={"source_type": "loan_tape"}, files={"file": ("loan_tape.csv", csv_data, "text/csv")}, headers=headers)
    second = client.post("/upload", data={"source_type": "loan_tape"}, files={"file": ("loan_tape.csv", csv_data, "text/csv")}, headers=headers)
    assert first.status_code == 200
    assert second.status_code == 200
    with SessionLocal() as db:
        count = db.execute(text("SELECT COUNT(*) FROM loans WHERE loan_id = 'L-6001' ")).scalar_one()
        source_count = db.execute(text("SELECT COUNT(*) FROM loan_sources WHERE loan_id = 'L-6001' ")).scalar_one()
        assert count == 1
        assert source_count == 2


def test_upload_creates_audit_events():
    reset_db()
    csv_data = "loan_id,borrower_id,origination_date,original_principal,current_balance,term_months\nL-7001,B-007,2024-07-01,150000,145000,180\n"
    client = TestClient(app)
    headers = _authenticate_data_operator(client)
    response = client.post(
        "/upload",
        data={"source_type": "loan_tape"},
        files={"file": ("loan_tape.csv", csv_data, "text/csv")},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    with SessionLocal() as db:
        events = db.execute(text("SELECT event_type, details FROM audit_logs ORDER BY id")).fetchall()
        assert any(event[0] == "file_uploaded" for event in events)
        assert any(event[0] == "loan_imported" for event in events)
