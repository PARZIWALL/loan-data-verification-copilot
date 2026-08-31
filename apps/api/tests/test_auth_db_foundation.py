import os

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_loan_verification.db")

import pytest
from fastapi.testclient import TestClient

from app.core.database import Base, SessionLocal, create_db_and_tables
from app.core.seed import seed_users
from app.models.user import User
from app.main import app


@pytest.fixture(scope="module")
def db_session():
    create_db_and_tables()
    seed_users()
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def test_database_models_initialize():
    tables = sorted(Base.metadata.tables.keys())
    assert "users" in tables
    assert "loan_sources" in tables
    assert "loans" in tables
    assert "validation_results" in tables
    assert "exceptions" in tables
    assert "review_actions" in tables
    assert "ai_recommendations" in tables
    assert "verified_loans" in tables
    assert "audit_logs" in tables


def test_seed_users_exist_for_all_roles(db_session):
    roles = {user.role for user in db_session.query(User).all()}
    assert {"data_operator", "reviewer", "data_consumer"}.issubset(roles)
    assert db_session.query(User).count() >= 3


def test_valid_login_returns_token_and_role():
    client = TestClient(app)
    response = client.post(
        "/auth/login",
        json={"username": "data_operator", "password": "data_operator_dev"},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert "access_token" in payload
    assert payload["user"]["role"] == "data_operator"
    assert payload["user"]["username"] == "data_operator"


def test_invalid_credentials_are_rejected():
    client = TestClient(app)
    response = client.post(
        "/auth/login",
        json={"username": "data_operator", "password": "wrong-password"},
    )
    assert response.status_code == 401


def test_role_information_is_available_to_protected_endpoints():
    client = TestClient(app)
    login_response = client.post(
        "/auth/login",
        json={"username": "reviewer", "password": "reviewer_dev"},
    )
    token = login_response.json()["access_token"]
    response = client.get(
        "/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["role"] == "reviewer"
    assert payload["username"] == "reviewer"
