"""Generate the demo loan tape, servicer update, and document manifest.

The competition brief (§5) asks for a synthetic dataset "modeled on public loan-level
schemas", and (§4) points at the Freddie Mac Single-Family Loan Performance sample as
schema inspiration. So rather than inventing numbers, this script reads the real sample
committed at the repo root, extracts genuine loan attributes (rates, balances, terms,
FICOs, states, maturities), and builds a canonical loan tape from them.

The Freddie file cannot be ingested directly: it is pipe-delimited with no header, 108
positional fields, and one row per loan per month. Eight distinct loans appear in it.
Those eight are used verbatim as realism anchors; the rest are drawn from the same
observed distributions.

Defects are then injected deliberately, one per loan, so every validation rule has a
visible example in the demo. Output is deterministic (fixed seed) so the demo is
reproducible run to run.

Usage:  python scripts/generate_demo_data.py
"""

from __future__ import annotations

import csv
import random
from datetime import date, datetime, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
FREDDIE_SAMPLE = REPO_ROOT / "sf-loan-performance-data-sample.csv"
DATA_DIR = REPO_ROOT / "data"

SEED = 20260831
TOTAL_LOANS = 40

LOAN_TAPE_COLUMNS = [
    "loan_id", "borrower_id", "loan_type", "origination_date", "maturity_date",
    "original_principal", "current_balance", "interest_rate", "term_months",
    "borrower_state", "loan_purpose", "credit_grade", "employment_length",
    "income_band", "payment_status", "days_past_due", "servicer_name",
    "last_payment_date", "last_updated_at", "document_status", "source_system",
]

SERVICERS = ["Meridian Loan Servicing", "Atlas Residential", "Cornerstone Servicing", "Northgate Capital"]
PURPOSES = ["purchase", "refinance", "cash_out_refinance", "home_improvement"]
INCOME_BANDS = ["low", "moderate", "middle", "upper_middle", "high"]


def _yyyymm_to_date(value: str, day: int = 1) -> date | None:
    value = value.strip()
    if len(value) != 6:
        return None
    return date(int(value[2:]), int(value[:2]), day)


def read_freddie_anchors() -> list[dict]:
    """Extract one canonical record per distinct loan from the Freddie sample."""
    if not FREDDIE_SAMPLE.exists():
        raise SystemExit(f"Freddie sample not found at {FREDDIE_SAMPLE}")

    by_loan: dict[str, list[list[str]]] = {}
    with FREDDIE_SAMPLE.open(newline="", encoding="utf-8") as handle:
        for row in csv.reader(handle, delimiter="|"):
            if len(row) > 34 and row[1].strip():
                by_loan.setdefault(row[1].strip(), []).append(row)

    anchors = []
    for rows in by_loan.values():
        first = rows[0]
        origination = _yyyymm_to_date(first[13])
        maturity = _yyyymm_to_date(first[18])
        anchors.append(
            {
                "interest_rate": float(first[7]) / 100.0,  # engine expects a 0-1 fraction
                "original_principal": float(first[9]),
                "term_months": int(first[12]),
                "credit_score": int(first[23]) if first[23].strip() else 700,
                "borrower_state": first[30].strip(),
                "loan_type": "fixed_rate" if first[34].strip() == "FRM" else "adjustable_rate",
                "origination_date": origination,
                "maturity_date": maturity,
            }
        )
    return anchors


def credit_grade(score: int) -> str:
    if score >= 780:
        return "A"
    if score >= 740:
        return "B"
    if score >= 700:
        return "C"
    if score >= 660:
        return "D"
    return "E"


def build_loans(anchors: list[dict]) -> list[dict]:
    rng = random.Random(SEED)
    today = date.today()
    states = [a["borrower_state"] for a in anchors if a["borrower_state"] != "PR"]

    loans: list[dict] = []
    for index in range(TOTAL_LOANS):
        anchor = anchors[index % len(anchors)]
        loan_id = f"L-{1001 + index}"

        if index < len(anchors):
            # The eight real Freddie loans, used verbatim.
            principal = anchor["original_principal"]
            rate = anchor["interest_rate"]
            term = anchor["term_months"]
            score = anchor["credit_score"]
            state = anchor["borrower_state"]
            origination = anchor["origination_date"]
            maturity = anchor["maturity_date"]
        else:
            # Drawn from the observed distributions, not invented from nothing.
            principal = round(rng.uniform(55_000, 620_000), -3)
            rate = round(rng.uniform(0.04375, 0.05875), 5)
            term = rng.choice([180, 240, 360])
            score = rng.randint(660, 800)
            state = rng.choice(states)
            origination = date(rng.randint(2015, 2023), rng.randint(1, 12), 1)
            maturity = date(origination.year + term // 12, origination.month, 1)

        paid_fraction = rng.uniform(0.55, 0.95)
        loans.append(
            {
                "loan_id": loan_id,
                "borrower_id": f"B-{2001 + index}",
                "loan_type": anchor["loan_type"],
                "origination_date": origination.isoformat(),
                "maturity_date": maturity.isoformat(),
                "original_principal": f"{principal:.2f}",
                "current_balance": f"{principal * paid_fraction:.2f}",
                "interest_rate": f"{rate:.5f}",
                "term_months": str(term),
                "borrower_state": state,
                "loan_purpose": rng.choice(PURPOSES),
                "credit_grade": credit_grade(score),
                "employment_length": str(rng.randint(1, 25)),
                "income_band": rng.choice(INCOME_BANDS),
                "payment_status": "current",
                "days_past_due": "0",
                "servicer_name": rng.choice(SERVICERS),
                "last_payment_date": (today - timedelta(days=rng.randint(5, 40))).isoformat(),
                "last_updated_at": (today - timedelta(days=rng.randint(1, 30))).isoformat(),
                "document_status": "complete",
                "source_system": "loan_tape",
            }
        )
    return loans


def inject_defects(loans: list[dict]) -> list[dict]:
    """Give every validation rule one visible example.

    Each defect targets a distinct loan so the exception queue reads as a clear list of
    independent problems rather than one loan failing everything.
    """
    by_id = {loan["loan_id"]: loan for loan in loans}
    today = date.today()

    # L-1001 stays clean here; servicer_update.csv contradicts it -> source_conflict.
    by_id["L-1001"]["current_balance"] = "95000.00"
    by_id["L-1001"]["original_principal"] = "155000.00"

    # balance_gt_principal
    by_id["L-1002"]["original_principal"] = "250000.00"
    by_id["L-1002"]["current_balance"] = "300000.00"

    # missing_document_status
    by_id["L-1003"]["document_status"] = ""

    # invalid_state_code -- a real Freddie loan in Puerto Rico, which the rule's
    # 50-state list does not cover. A genuine gap surfaced by real data.
    by_id["L-1004"]["borrower_state"] = "PR"

    # stale_record
    by_id["L-1005"]["last_updated_at"] = (today - timedelta(days=1100)).isoformat()

    # duplicate_borrower_amount_date -- same borrower, principal and origination date
    for loan_id in ("L-1006", "L-1007"):
        by_id[loan_id]["borrower_id"] = "B-DUPLICATE"
        by_id[loan_id]["original_principal"] = "180000.00"
        by_id[loan_id]["origination_date"] = "2019-06-01"

    # closed_positive_balance
    by_id["L-1008"]["payment_status"] = "closed"
    by_id["L-1008"]["current_balance"] = "5000.00"

    # payment_status_dpd_consistency
    by_id["L-1009"]["payment_status"] = "current"
    by_id["L-1009"]["days_past_due"] = "45"

    # negative_original_principal
    by_id["L-1010"]["original_principal"] = "-5000.00"

    # maturity_after_origination
    by_id["L-1011"]["origination_date"] = "2022-05-01"
    by_id["L-1011"]["maturity_date"] = "2020-05-01"

    # interest_rate_range (engine allows 0.0-1.0; 12.5 is clearly out of range)
    by_id["L-1012"]["interest_rate"] = "12.5"

    # valid_payment_status
    by_id["L-1013"]["payment_status"] = "not_a_real_status"

    # A row that cannot be normalized at all -> import failure, not a validation failure.
    # Appended as a raw dict so it is written verbatim.
    malformed = dict(by_id["L-1040"])
    malformed["loan_id"] = "L-1041"
    malformed["borrower_id"] = "B-2041"
    malformed["original_principal"] = "not-a-number"
    loans.append(malformed)

    return loans


def build_servicer_update(loans: list[dict]) -> list[dict]:
    """Later servicer figures: some conflicting, most agreeing.

    Most rows must agree, otherwise conflict detection is trivially true and the demo
    proves nothing.
    """
    by_id = {loan["loan_id"]: loan for loan in loans}
    rows = []

    # The hero conflict: canonical says 95000, the servicer says 82000.
    rows.append({
        "loan_id": "L-1001", "current_balance": "82000.00", "payment_status": "current",
        "days_past_due": "0", "last_updated_at": date.today().isoformat(),
    })
    # Two further genuine conflicts.
    rows.append({
        "loan_id": "L-1014", "current_balance": "64250.00", "payment_status": "current",
        "days_past_due": "0", "last_updated_at": date.today().isoformat(),
    })
    rows.append({
        "loan_id": "L-1015", "current_balance": by_id["L-1015"]["current_balance"],
        "payment_status": "delinquent", "days_past_due": "62",
        "last_updated_at": date.today().isoformat(),
    })
    # Agreeing rows.
    for loan_id in ("L-1016", "L-1017", "L-1018", "L-1019", "L-1020"):
        loan = by_id[loan_id]
        rows.append({
            "loan_id": loan_id, "current_balance": loan["current_balance"],
            "payment_status": loan["payment_status"], "days_past_due": loan["days_past_due"],
            "last_updated_at": loan["last_updated_at"],
        })
    return rows


def build_document_manifest(loans: list[dict]) -> list[dict]:
    rows = []
    for loan in loans[:20]:
        status = "pending" if loan["loan_id"] == "L-1003" else "received"
        rows.append({
            "loan_id": loan["loan_id"],
            "document_type": "credit_file",
            "doc_status": status,
        })
    rows.append({"loan_id": "L-1003", "document_type": "appraisal", "doc_status": "missing"})
    return rows


def write_csv(path: Path, columns: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)
    print(f"  wrote {path.relative_to(REPO_ROOT)} ({len(rows)} rows)")


def main() -> None:
    anchors = read_freddie_anchors()
    print(f"Extracted {len(anchors)} real loans from the Freddie Mac sample")

    loans = inject_defects(build_loans(anchors))
    servicer = build_servicer_update(loans)
    manifest = build_document_manifest(loans)

    print("Writing demo dataset:")
    write_csv(DATA_DIR / "loan_tape.csv", LOAN_TAPE_COLUMNS, loans)
    write_csv(
        DATA_DIR / "servicer_update.csv",
        ["loan_id", "current_balance", "payment_status", "days_past_due", "last_updated_at"],
        servicer,
    )
    write_csv(
        DATA_DIR / "document_manifest.csv",
        ["loan_id", "document_type", "doc_status"],
        manifest,
    )


if __name__ == "__main__":
    main()
