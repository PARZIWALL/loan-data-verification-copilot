"""FastAPI application entry point."""

from fastapi import FastAPI

app = FastAPI(title="Loan Data Verification Copilot", version="0.1.0")


@app.get("/health", tags=["health"])
def health_check() -> dict[str, str]:
    """Return service health for local development and orchestration."""
    return {"status": "ok"}
