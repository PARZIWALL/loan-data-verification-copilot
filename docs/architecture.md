# Architecture

Describes what is built. For setup and usage see the top-level `README.md`.

## Shape

A single FastAPI application over one relational database, deliberately kept as a strong
monolith so the verification workflow stays readable end to end. No microservices, no event
bus, no CQRS layering, no vector database, no agent framework.

```
apps/api/app
  api/          HTTP only: routing, auth, role checks, status codes
  services/     workflow orchestration (the bulk of the logic)
  validators/   the deterministic rule engine and its 17 rules
  ingestion/    CSV parsing, normalization, lineage
  models/       SQLAlchemy models
  schemas/      Pydantic request/response contracts
  audit/        append-only event logging
  core/         config, database, security, seeding
```

There is no repository layer. Services take a SQLAlchemy `Session` and query directly; the
session is owned by the request and passed down, which is what makes the single-transaction
guarantees below possible.

## Core invariant: the AI safety boundary

**AI can recommend. AI cannot mutate canonical data.**

The only path to a canonical change is:

```
AI -> ai_recommendations -> human reviewer -> review_actions -> loans
```

This is enforced in code, not by convention. `ai_recommendation_service` writes only to
`ai_recommendations` and `audit_logs`. When a reviewer accepts a recommendation,
`ai_disposition_service` applies the change by calling the ordinary reviewer edit path
(`exception_service.edit_exception_field`) — so the editable-field allowlist, value
normalization, the `field_edited` audit event, and revalidation all apply to an AI-driven
correction exactly as they do to a hand-typed one. The AI cannot reach a field a reviewer
could not have edited themselves.

## Data model

| Table | Holds |
|---|---|
| `users` | Identity and one of `data_operator`, `reviewer`, `data_consumer` |
| `loan_sources` | Every ingested raw row, verbatim, with file/system/row-number lineage |
| `loans` | The canonical current state of a loan, keyed by `loan_id` |
| `validation_results` | One row per rule per run, with severity, message and details |
| `exceptions` | Reviewable failures, with a lifecycle status |
| `ai_recommendations` | Persisted recommendations, their evidence snapshot, and reviewer disposition |
| `review_actions` | Every human action, optionally linked to the recommendation that prompted it |
| `verified_loans` | Immutable post-review snapshots with a SHA-256 fingerprint |
| `audit_logs` | Append-only event trail |

`loans` and `loan_sources` reference each other (`loan_sources.loan_id` and
`loans.primary_source_id`). This cycle is why the initial migration adds the second
constraint with `batch_alter_table` after both tables exist rather than inline.

### Text storage policy

Bounded identifiers, enums, codes, hashes and ISO-8601 timestamps use `String(n)`. Free text
of unpredictable length uses `Text`. Never cap free text with `String(n)`: SQLite silently
ignores the limit while PostgreSQL raises, so a guessed cap is a latent production failure
local tests cannot catch. Product-level length limits belong at the API boundary, not in
storage.

`tests/test_schema_parity_8a.py` runs the migrations into a temporary database and asserts
`compare_metadata` finds no difference against the models, so schema drift fails a test
rather than surfacing in production.

## Lifecycle

### 1. Ingestion

`POST /upload` (data_operator only) parses the CSV, writes every row to `loan_sources`
verbatim, then normalizes `loan_tape` rows into `loans`. Rows that cannot be normalized are
retained with `import_status="failed"` and a reason, and reported in the upload summary —
a bad row never silently disappears.

Source precedence is descriptive, not an override rule: `loan_tape.csv` is the primary system
of record; `servicer_update.csv` and `document_manifest.csv` are secondary and supporting
evidence. A later source never automatically wins.

Validation runs at the end of the same transaction, once per unique touched loan.

### 2. Validation

`validators/engine.py` executes registered rules in a deterministic phase order and persists
one `validation_results` row per rule. All 17 rules live in `validators/rules/__init__.py`.

Two entry points share one implementation: `validate_loan(loan_id)` opens and commits its own
session, while `validate_loan_in_session(db, loan_id)` runs inside the caller's transaction.
The second exists so ingestion and reviewer edits can validate atomically with the mutation
that triggered them.

Severity is `critical`, `high`, `medium`, `low`.

### 3. Exceptions

A failing rule creates an exception, or reuses the existing one for that loan and rule.
Reuse is deliberate and has two branches:

- An `open` or `in_review` exception is reused, so repeated failures do not pile up duplicates.
- A `resolved`/`rejected` exception is reused **only if a human decided it** (an `approve` or
  `reject` review action exists). Otherwise a fresh exception is created, which preserves the
  tested pass-then-fail-again behaviour.

Without that second branch, an exception a reviewer had explicitly approved would be silently
duplicated every time an unrelated edit triggered a full revalidation.

Historical validation results and exceptions are never deleted.

### 4. Human review

Reviewer-only: comment, edit an allowlisted field, approve, reject, request correction.

```
open ──approve──────────> resolved (terminal)
  │  ──reject───────────> rejected (terminal)
  │  ──request-correction> in_review
in_review ─> same three transitions
```

A field edit mutates the loan, records a `review_action`, emits `field_edited`, and revalidates
— all in one transaction. If revalidation fails, the whole operation rolls back; there is no
state where the edit landed but the revalidation did not.

### 5. AI copilot

Three stages, each with a distinct job.

**Evidence packet** (`ai_evidence_service`) — read-only and deterministic. For a given
exception it assembles the canonical loan, the failing rule's definition and relevant fields,
the original *and* latest validation results plus full history, per-field provenance
(canonical value, primary source record, secondary sources), bounded raw source evidence,
related duplicate records, review history, schema and relationship metadata, and the reviewer
editable-field allowlist. Raw source payloads are capped and truncation is explicit — source
identifiers are never dropped. A `data_trust_boundary` section marks source content as
untrusted data rather than instruction. Identical database state always yields an identical
packet.

The exception's own FK points at the result that first created it, which revalidation never
repoints, so `original` and `latest` are surfaced separately rather than conflated.

**Recommendation** (`ai_recommendation_service`) — sends the packet to Groq
(`openai/gpt-oss-120b`) with a JSON-Schema-constrained response, then re-validates the reply
against the packet:

- Citations must resolve to real source rows and real fields in the packet.
- Corrections must name a reviewer-editable field and a value the reviewer edit normalizer
  can represent.
- A suggested value must already appear in that field's evidence. A well-formed but
  unsupported correction is **downgraded** to `request_human_review` with confidence capped
  at 0.39 and the reason recorded — not silently trusted.

Nothing is persisted unless every check passes. One retry for transient provider errors only.
The full packet is stored alongside the recommendation, so any inference stays reproducible.

**Disposition** (`ai_disposition_service`) — a reviewer accepts, edits or rejects. Only a
`pending` recommendation can be dispositioned. A disposition decides the *recommendation*,
never the *exception*: it never approves, rejects or resolves. The one status change it can
cause is indirect and correct — an applied correction triggers revalidation, and a
now-passing rule resolves its exception through the normal path.

Accepting a `request_human_review` recommendation records agreement that the AI was right to
decline. It changes no data and does not close the exception.

### 6. Verification, hashing, export

A loan is eligible only if it has been validated at least once and has no `open`, `in_review`
or `rejected` exception. Verification writes an immutable snapshot and computes a SHA-256 over
a canonical JSON serialization (sorted keys, compact separators, UTF-8) of exactly
`final_data`, `source_reference` and `validation_result_summary`. Later changes to the live
loan do not affect it.

Export serves the stored snapshot, marks the record exported, and audits the event. It never
recomputes the hash and never re-reads the current loan.

### 7. Audit

Append-only, written in the same transaction as the action it records: `file_uploaded`,
`loan_imported`, `validation_executed`, `exception_created`, `exception_resolved`,
`reviewer_comment_added`, `field_edited`, `loan_approved`, `loan_rejected`,
`correction_requested`, `ai_recommendation_created`, `ai_recommendation_dispositioned`,
`verified_record_created`, `verified_record_exported`.

The disposition event carries what the AI proposed *and* what was actually applied, so
"AI recommended X, reviewer did Y, this changed" is reconstructable.

## API

All routes require a bearer token except `/health` and `/auth/login`.

| Method | Path | Role |
|---|---|---|
| POST | `/auth/login` | public |
| GET | `/auth/me` | any |
| GET | `/health` | public |
| POST | `/upload` | data_operator |
| GET | `/loans` | any |
| GET | `/loans/{loan_id}` | any |
| POST | `/loans/{loan_id}/revalidate` | any |
| GET | `/exceptions` | any |
| GET | `/exceptions/{id}` | any |
| POST | `/exceptions/{id}/comment` | reviewer |
| POST | `/exceptions/{id}/edit` | reviewer |
| POST | `/exceptions/{id}/approve` | reviewer |
| POST | `/exceptions/{id}/reject` | reviewer |
| POST | `/exceptions/{id}/request-correction` | reviewer |
| POST | `/exceptions/{id}/ai-recommendation` | reviewer |
| POST | `/ai-recommendations/{id}/accept` | reviewer |
| POST | `/ai-recommendations/{id}/edit` | reviewer |
| POST | `/ai-recommendations/{id}/reject` | reviewer |
| POST | `/verified-loans` | reviewer |
| GET | `/verified-loans` | any |
| GET | `/verified-loans/{id}` | any |
| POST | `/verified-loans/{id}/export` | reviewer, data_consumer |
| GET | `/summary` | any |
| GET | `/audit/{loan_id}` | any |

`POST /verified-loans` returns HTTP 200 for both success and ineligibility — an ineligible
loan is a normal workflow outcome carrying the blocking exceptions, not an error. Verifying
an already-verified loan returns 409.

## Startup

The app creates tables and seeds the three role users on startup (`AUTO_INIT_DB`, default on)
so a fresh checkout runs without a migration step. CORS origins come from `CORS_ORIGINS`
because the frontend is served separately. Validation rules are registered explicitly at
startup, with a lazy self-heal in the engine as a backstop.

## Trade-offs

- **No repository layer.** Services use the session directly. The indirection would buy
  nothing here and would complicate the single-transaction guarantees.
- **Timestamps are ISO-8601 strings, not `DateTime`.** Consistent across all nine tables.
  Converting them now would change ordering semantics and alter the hash input, invalidating
  every existing `record_hash`.
- **Ingestion validates synchronously.** Simple and correct; not a production ingestion path
  at scale.
- **PostgreSQL is unverified at runtime.** Compatible by construction and by migration fixes,
  but only SQLite has actually been exercised.
