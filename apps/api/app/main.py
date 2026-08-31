"""FastAPI application entry point."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.audit import router as audit_router
from app.api.auth import router as auth_router
from app.api.exceptions import router as exceptions_router
from app.api.loans import router as loans_router
from app.api.summary import router as summary_router
from app.api.verification import router as verification_router
from app.core.config import settings
from app.core.database import create_db_and_tables
from app.core.seed import seed_users
from app.validators import rules as _default_validation_rules  # noqa: F401  (registers default rules on import)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Make a fresh checkout runnable.

    Without this the schema and the three role users only ever existed because the test
    suite created them, so starting the app against a new database and calling any real
    endpoint failed with "no such table: users".
    """
    if settings.AUTO_INIT_DB:
        create_db_and_tables()
        seed_users()
    yield


app = FastAPI(title="Loan Data Verification Copilot", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(exceptions_router)
app.include_router(loans_router)
app.include_router(verification_router)
app.include_router(summary_router)
app.include_router(audit_router)


@app.get("/health", tags=["health"])
def health_check() -> dict[str, str]:
    """Return service health for local development and orchestration."""
    return {"status": "ok"}
