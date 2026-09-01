# Loan Data Verification Copilot

Turns messy loan tapes into validated, traceable, verified data. Records are ingested with
full source lineage, checked by a deterministic rule engine, triaged through a reviewer
exception queue with an evidence-grounded AI copilot, and frozen into tamper-evident
verified records with a SHA-256 fingerprint.

The AI can recommend. Only a human can act.

## Live deployment

| Component | Where |
|---|---|
| Frontend | https://loan-data-frontend.vercel.app |
| Backend API | Hosted on Render |

The frontend calls the Render-hosted API directly; no separate setup is needed to try the
live version. For full control (seeding your own demo data, running tests, using your own
`GROQ_API_KEY`), run it locally — see **Setup** below.

## What it does

```
CSV upload -> raw source rows (lineage preserved) -> canonical loan
     -> deterministic validation (17 rules) -> exceptions
     -> reviewer review: comment / edit / approve / reject / request correction
        +-- AI copilot: evidence packet -> recommendation -> reviewer accepts, edits or rejects
     -> revalidation -> verified snapshot -> SHA-256 hash -> JSON export
     -> every step appended to an audit trail
```

## Roles

| Role | Can |
|---|---|
| `data_operator` | Upload CSVs, view loans and import results |
| `reviewer` | Work the exception queue, edit allowlisted fields, request AI recommendations and accept/edit/reject them, approve/reject exceptions, verify loans |
| `data_consumer` | Read verified records, audit trails, export verified JSON |

Roles are enforced server-side on every mutating endpoint; the frontend hides out-of-role
navigation but the API is the authority.

## Test credentials

Seeded automatically on first startup:

| Username | Password |
|---|---|
| `data_operator` | `data_operator_dev` |
| `reviewer` | `reviewer_dev` |
| `data_consumer` | `data_consumer_dev` |

These are development credentials. Passwords are unsalted SHA-256 — production-grade auth
is explicitly out of scope for this project.

## Setup

### Backend

```bash
cd apps/api
python -m venv .venv
.venv/Scripts/activate          # Windows
# source .venv/bin/activate     # macOS/Linux
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

On startup the app creates its tables and seeds the three role users, so a fresh clone is
runnable with no migration step. Interactive API docs at `http://localhost:8000/docs`.

### Frontend

```bash
cd apps/web
cp .env.local.example .env.local
npm install
npm run dev                     # http://localhost:3000
```

### Demo data

```bash
python scripts/generate_demo_data.py   # regenerate CSVs into data/ (optional; already committed)
python scripts/seed_demo.py            # load them through the real /upload API
```

`seed_demo.py` uploads via the real endpoint rather than writing to the database, so the
demo state is produced by the actual pipeline. It yields 40 loans and 18 open exceptions
across 12 rule types, with a data-quality score of 0.625.

The dataset is synthetic but derived from `sf-loan-performance-data-sample.csv`, the Freddie
Mac Single-Family Loan Performance sample referenced in the brief. Eight real loans are used
verbatim as realism anchors (their actual rates, balances, terms, credit scores and states);
the remaining 32 are drawn from the same distributions. Defects are then injected
deliberately, one per loan, so every rule has a visible example.

Fannie Mae's equivalent dataset was not used: the brief lists both as optional stretch
sources and explicitly recommends a synthetic organizer-style package for judging, and
Fannie Mae's portal is registration-gated while Freddie Mac's sample file was directly
available. Freddie Mac alone was sufficient for schema and value realism.

## Environment variables

Backend (`apps/api/.env`, see `.env.example`):

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | `sqlite:///./loan_verification.db` | SQLite by default; PostgreSQL supported via SQLAlchemy |
| `JWT_SECRET_KEY` | dev placeholder | Change for any shared deployment |
| `JWT_ALGORITHM` | `HS256` | |
| `JWT_ACCESS_TOKEN_EXPIRE_MINUTES` | `60` | |
| `GROQ_API_KEY` | *(empty)* | Required for AI recommendations; without it that endpoint fails closed |
| `CORS_ORIGINS` | `localhost:3000,127.0.0.1:3000,localhost:5173` | Browser origins allowed to call the API |
| `AUTO_INIT_DB` | `true` | Create tables and seed users on startup |

Frontend (`apps/web/.env.local`): `NEXT_PUBLIC_API_BASE_URL`, default `http://localhost:8000`.

## AI setup

- **Provider:** Groq, via the OpenAI-compatible SDK
- **Base URL:** `https://api.groq.com/openai/v1`
- **Model:** `openai/gpt-oss-120b`
- **Prompt version:** `loan-review-v1`, stored with every recommendation

Set `GROQ_API_KEY` in `apps/api/.env`. Without it the app runs normally and only the AI
recommendation endpoint returns an error — nothing else degrades.

Safety properties, all enforced in code and covered by tests:

- The model's only input is the read-only evidence packet built for that one exception.
- Output is constrained by a JSON Schema at the provider layer, then re-validated with Pydantic.
- Citations are checked against the packet; a plausible-but-fabricated source row is rejected.
- Corrections are restricted to the reviewer-editable allowlist, and the proposed value must
  already appear in the packet's evidence. A well-formed but unsupported correction is
  **downgraded** to `request_human_review` rather than trusted.
- The AI never writes to loans, exceptions, validation results or verified records.

See `docs/ai_evaluation.md` for a scored evaluation across eight exception types.

## Running tests

```bash
cd apps/api
python -m pytest -q
```

No network and no API key required — the Groq client is stubbed throughout.

```bash
cd apps/web
npm run build                  # type-check and production build
```

## Demo flow

1. Sign in as **data_operator** and upload `data/loan_tape.csv`. The import summary shows
   40 imported and 1 row rejected (`not-a-number` cannot be normalized). Validation runs
   automatically.
2. Upload `data/servicer_update.csv` — source conflicts surface on their own.
3. **Dashboard** shows the validation summary and how many loans need correction.
4. Sign in as **reviewer**, open **Exception Queue**, and open the `source_conflict` on **L-1001**.
5. The source comparison shows canonical `95000` and `loan_tape.csv` `95000` against
   `servicer_update.csv` row 2 at `82000`.
6. **Generate AI recommendation** — a grounded correction citing the servicer row.
7. **Accept** — the field updates to 82000, revalidation runs, and the exception resolves.
8. Review history shows `ai_accept` and `edit_field`, both badged AI-assisted.
9. **Verify this loan** — immutable snapshot plus SHA-256 hash.
10. Sign in as **data_consumer**, open **Verified Records**, copy the hash, **Export JSON**,
    then view the loan's **Audit Trail**.

## Verified records, hashing and export

A loan can only be verified once it has been validated and has no unresolved exceptions
(`open`, `in_review` and `rejected` all block it). Verification writes an immutable snapshot:
canonical data at that moment, source reference, validation summary, reviewer decision,
verifier and timestamp.

The `record_hash` is a SHA-256 over a canonical JSON serialization (sorted keys, compact
separators, UTF-8) of exactly three components: `final_data`, `source_reference` and
`validation_result_summary`. Later edits to the live loan do not change it.

Export serves the stored snapshot — never a re-read of the current loan — marks the record
exported, and appends an audit event. Re-export is allowed and never recomputes the hash.

## Known limitations

- **PostgreSQL is unverified at runtime.** The schema and migrations are Postgres-compatible
  and the FK-ordering bug in the initial migration is fixed, but no Postgres instance was
  available during development. Only SQLite has been exercised. Do not treat Postgres as proven.
- **Auth is development-grade.** Unsalted SHA-256 password hashing, no refresh tokens, no
  rate limiting. Production-grade security is out of scope per the brief.
- **AI corrections are deliberately narrow.** Because a suggested value must already appear
  in the evidence, in practice only `source_conflict` yields an automated correction. Every
  other rule type resolves to `request_human_review`. This is intended — it is the
  anti-hallucination guarantee — but it means the copilot assists triage more than it auto-fixes.
- **Document manifest evidence is not merged into canonical data.** `document_manifest.csv`
  rows are stored and shown as evidence, but `doc_status` is never mapped onto the canonical
  `document_status` field, so it cannot ground a correction to it.
- **Re-uploading a loan tape overwrites reviewer edits.** Re-ingesting the same `loan_id`
  replaces every canonical field from the new row; a prior manual correction is lost.
- **Ingestion validates synchronously.** A 5,000-row upload runs validation for every touched
  loan inside the request. Fine at demo scale, not a production ingestion path.

## Layout

```
apps/api      FastAPI backend, SQLAlchemy models, validation engine, AI services
apps/web      Next.js 15 reviewer console (App Router, TypeScript, Tailwind)
data          Demo CSVs (loan tape, servicer update, document manifest)
docs          Architecture, AI development log, AI evaluation
scripts       Demo data generation, seeding, and AI evaluation
```

## Documentation

| Document | Contents |
|---|---|
| `docs/architecture.md` | System design, data model, lifecycle, API surface, trade-offs |
| `docs/AI_DEVELOPMENT_LOG.md` | How AI tooling was used to build this, prompts, rejected AI output, lessons |
| `docs/ai_evaluation.md` | Scored evaluation of the AI copilot across eight exception types |
| `docs/sample_output/` | Reference verified-record export and audit trail for `L-1001`, with a reproducible hash |
