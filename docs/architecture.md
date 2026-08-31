# Architecture lock

## Overview

The application follows a single-source-of-truth flow for loan verification:

raw sources -> normalized loan sources -> canonical loans -> validation -> exceptions -> human review -> verified loans -> audit trail

This repository is intentionally structured as a strong monolith so that the business workflow stays understandable and auditable.

## Core rule: AI safety boundary

AI can recommend. AI cannot mutate canonical data.

The mutation path is always:

AI -> ai_recommendations -> human reviewer -> review_actions -> loans

This invariant is enforced as a product rule, not a convenience choice.

## Domain model

### Users
- `users` stores identity and roles: `data_operator`, `reviewer`, and `data_consumer`.
- The role is checked at API/service boundaries before allowing review actions.

### Loan sources
- `loan_sources` stores raw uploaded row-level lineage.
- This table keeps the original `raw_data` JSONB payload and source metadata so that ingestion evidence is never lost.
- Primary source precedence is defined as `loan_tape.csv`, with `servicer_update.csv` and `document_manifest.csv` treated as secondary/supporting inputs.

### Canonical loans
- `loans` is the canonical current state of a loan.
- Raw CSV values are normalized before being written here.
- Source conflict evidence remains in `loan_sources` and `validation_results`, not silently overwritten.

### Validation and exceptions
- `validation_results` stores rule-level outcomes with severity and extra details.
- `exceptions` aggregates the reviewable failures.
- A failed rule should create an exception when it requires human review or adjudication.

### Review and AI
- `ai_recommendations` is the persistent, auditable recommendation layer.
- `review_actions` records the human review decision, including field edits and comments.
- AI output may suggest corrections but must not update canonical loan data directly.

### Verification and audit
- `verified_loans` holds a frozen snapshot of the loan state after review and approval.
- `audit_logs` records user/system/AI events for operational and compliance traceability.

## Validation lifecycle

The validator must support the required organizer problem categories, including:
- required field checks
- duplicate detection
- invalid date and state checks
- balance and principal sanity checks
- source conflict handling
- stale or suspicious borrower patterns
- missing document status
- closed loan with positive balance

Severity is standardized as `critical`, `high`, `medium`, and `low`.

## Review lifecycle

1. Upload raw data.
2. Parse and normalize into `loan_sources` and `loans`.
3. Run validators and record `validation_results`.
4. Convert failed validations into `exceptions`.
5. Create `ai_recommendations` for actionable exceptions.
6. Reviewer approves, rejects, comments, or edits the field.
7. Save the change in `review_actions`.
8. Revalidate the loan and resolve the exception.
9. Store a verified snapshot in `verified_loans`.
10. Write the audit event to `audit_logs`.

## API boundary

The API layer owns HTTP concerns only. The service layer owns workflow orchestration. The repository layer owns persistence.

Important endpoints:
- `POST /upload`
- `GET /loans`, `GET /loans/:id`
- `GET /exceptions`, `GET /exceptions/:id`
- `POST /exceptions/:id/comment`
- `POST /exceptions/:id/edit`
- `POST /exceptions/:id/approve`
- `POST /exceptions/:id/reject`
- `POST /loans/:id/revalidate`
- `GET /verified-loans`
- `GET /audit/:loanId`

## Out-of-scope decisions

This project intentionally avoids architectural bloat such as:
- microservices
- Kafka/event buses
- generic CQRS layering
- dynamic multi-tenant permissions engines
- agent swarms or vector DB pipelines

## Implementation direction

The repository is already organized around the right structure. The next implementation phase should focus on exposing and enforcing these contracts in actual code, with documentation and tests first so the architecture does not drift.
