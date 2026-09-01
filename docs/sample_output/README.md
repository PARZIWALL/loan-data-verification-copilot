# Sample output

Two artifacts showing what the system produces at the end of the verification workflow:

| File | Endpoint it corresponds to |
|---|---|
| `verified_loan_L-1001.json` | `POST /verified-loans/{id}/export` |
| `audit_trail_L-1001.json` | `GET /audit/L-1001` |

## Provenance — read this first

**These are illustrative reference outputs, not captured from a live run.** They were
hand-constructed to match the exact response shapes produced by
`app/services/verification_service.py` and `app/api/audit.py`.

The reason is honest and worth stating: at the time these were prepared, `L-1001` in the
working demo database still had unresolved exceptions, and verification is gated —
`POST /verified-loans` returns

```json
{"status": "ineligible", "reason": "Loan has unresolved exceptions", ...}
```

with **HTTP 200**, not a verified snapshot, until every blocking exception (`open`,
`in_review` or `rejected`) is cleared. Rather than bypass that gate to manufacture a
record, these files document what the stored snapshot *is* once the loan legitimately
passes it. The gate refusing to yield a record is the correct behaviour, and the reason
this directory exists in this form.

Every field name, nesting level and value type here is taken from the real code paths.
Values for `L-1001` come from the committed demo CSVs (`data/loan_tape.csv` row 2 and
`data/servicer_update.csv` row 2), so the scenario is the one the demo actually runs.

## The hash is real

`record_hash` in `verified_loan_L-1001.json` is **not** a placeholder. It was computed by
calling the shipped `compute_verified_record_hash()` over the three components in that
file, so it reproduces exactly:

```bash
python - <<'PY'
import json, sys
sys.path.insert(0, "apps/api")
from app.services.verification_service import compute_verified_record_hash

record = json.load(open("docs/sample_output/verified_loan_L-1001.json"))
recomputed = compute_verified_record_hash(
    record["final_data"],
    record["source_reference"],
    record["validation_result_summary"],
)
print(recomputed)
print("matches:", recomputed == record["record_hash"])
PY
```

→ `e11f92562eb9dfe1f52374d7da81de35dafaacecbf9436a96867dbd719eb0a64` · `matches: True`

Change any byte of `final_data`, `source_reference` or `validation_result_summary` and the
digest moves. That is the tamper-evidence property, demonstrable without a running server.

## What the verified record shows

- `current_balance` is **82000.0**, not the 95000.0 the loan tape carried. That is the
  AI-recommended, human-accepted correction, frozen into the snapshot.
- `validation_result_summary.total_results` is **51** — three validation runs of 17 rules
  (ingest, servicer-update ingest, post-edit revalidation). `failed: 1` is the historical
  `source_conflict` failure; `rule_statuses` reflects the latest run, where all 17 pass.
  History is kept, not overwritten.
- `reviewer_decision` is `null`. The exception was resolved by revalidation after the field
  edit, so no explicit approve/reject action was recorded. The field is populated only when
  a reviewer explicitly approves, rejects or requests a correction.
- `source_records_count` is 3: `loan_tape.csv` row 2, `servicer_update.csv` row 2, and the
  `document_manifest.csv` row for this loan.

## What the audit trail shows

Twelve events across the full lifecycle, and the ordering is the point: an AI
recommendation is created, a human disposes of it, *then* the field changes. The
`field_edited` event carries `ai_recommendation_id`, which is what makes an AI-assisted
change distinguishable from a manual one after the fact.

`file_uploaded` events do not appear here — they are logged without a `loan_id` because
they describe a file rather than a loan, so a per-loan trail correctly excludes them. The
per-loan record of ingestion is `loan_imported`.
