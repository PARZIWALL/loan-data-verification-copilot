# Loan Data Verification Copilot

Backend-first Python project for ingesting loan data, identifying validation exceptions,
supporting AI-assisted review, and preserving an auditable human decision trail.

## Layout

- `apps/api`: FastAPI backend and domain logic.
- `data`: raw, processed, and sample datasets (not committed except placeholders).
- `docs`: architecture, API, and AI-development notes.
- `scripts`: local data and benchmark utilities.

The frontend will be added later. The first implementation milestone is CSV ingestion,
canonical loan normalization, validation, exception persistence, and API exposure.
