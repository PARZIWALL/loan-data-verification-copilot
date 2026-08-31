from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models.user import User


DEV_PASSWORDS = {
    "data_operator": "data_operator_dev",
    "reviewer": "reviewer_dev",
    "data_consumer": "data_consumer_dev",
}


def hash_password(password: str) -> str:
    import hashlib

    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def seed_users() -> None:
    db: Session = SessionLocal()
    try:
        for role, password in DEV_PASSWORDS.items():
            user = db.query(User).filter(User.username == role).one_or_none()
            if user is None:
                db.add(User(username=role, password_hash=hash_password(password), role=role))
        db.commit()
    finally:
        db.close()
