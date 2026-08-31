"""Validation rule execution engine."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.audit.service import log_audit_event
from app.core.database import SessionLocal
from app.models.loan import Loan
from app.models.loan_source import LoanSource
from app.models.validation_result import ValidationResult
from app.services.exception_service import create_or_reuse_exception_for_validation_result, resolve_open_exceptions_for_pass_result

VALIDATION_PHASE_ORDER = {
    "required": 0,
    "numeric": 1,
    "date": 2,
    "identity": 3,
    "status": 4,
    "document": 5,
    "cross_source": 6,
}

_registered_rules: list[dict[str, Any]] = []
_rule_sequence = 0


def register_rule(
    rule_name: str,
    rule_fn: Callable[[dict[str, Any]], dict[str, Any]],
    *,
    phase: str = "required",
    order: int | None = None,
) -> str:
    """Register a validation rule for deterministic execution."""
    if not callable(rule_fn):
        raise TypeError("Validation rules must be callable.")

    global _rule_sequence
    phase_index = VALIDATION_PHASE_ORDER.get(phase, len(VALIDATION_PHASE_ORDER))
    sorted_order = order if order is not None else _rule_sequence
    _rule_sequence += 1
    _registered_rules.append(
        {
            "name": rule_name,
            "fn": rule_fn,
            "phase": phase,
            "phase_index": phase_index,
            "order": sorted_order,
        }
    )
    return rule_name


def clear_rules() -> None:
    """Clear registered validation rules for isolated tests and resets."""
    _registered_rules.clear()
    global _rule_sequence
    _rule_sequence = 0


def _get_rules_in_order() -> list[dict[str, Any]]:
    return sorted(
        _registered_rules,
        key=lambda item: (item["phase_index"], item["order"], item["name"]),
    )


def _normalize_rule_result(
    rule_name: str,
    raw_result: dict[str, Any],
    context: dict[str, Any],
) -> dict[str, Any]:
    if not isinstance(raw_result, dict):
        raise TypeError(f"Rule {rule_name} must return a dictionary-like validation result.")

    result = dict(raw_result)
    result["rule_name"] = result.get("rule_name") or rule_name
    result["loan_id"] = result.get("loan_id") or context["loan"].loan_id
    result["run_at"] = result.get("run_at") or context["run_at"]
    result["status"] = str(result.get("status") or "pass").lower()
    if result["status"] not in {"pass", "fail"}:
        raise ValueError(f"Rule {rule_name} returned invalid status '{result['status']}'.")
    result["severity"] = result.get("severity") or "medium"
    result["message"] = result.get("message") or "Validation rule executed."
    result["details"] = result.get("details") or {}
    return result


def _ensure_rules_registered() -> None:
    """Defensive guard: register the default rule set if nothing is registered.

    Application startup registers rules explicitly (see app.main). This guard exists
    only so validation can never silently run against an empty registry -- e.g. if a
    test's teardown calls clear_rules() and a later caller runs validation before
    anything re-registers the default set. Deferred import avoids a circular import
    with app.validators.rules (which imports register_rule from this module).
    """
    if not _registered_rules:
        from app.validators.rules import register_default_rules

        register_default_rules()


def _execute_validation(db: Session, loan_id: str) -> list[dict[str, Any]]:
    """Run every registered rule for a loan against the given session and persist results.

    Does not commit, rollback, or close the session -- the caller owns the transaction
    boundary, so this can be composed into a larger unit of work (e.g. an ingestion or
    a reviewer edit) instead of always running in its own isolated transaction.
    """
    _ensure_rules_registered()

    loan = db.get(Loan, loan_id)
    if loan is None:
        raise LookupError(f"Loan {loan_id} not found.")

    run_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    source_rows = (
        db.query(LoanSource)
        .filter(LoanSource.loan_id == loan_id)
        .order_by(LoanSource.id)
        .all()
    )

    context: dict[str, Any] = {
        "loan": loan,
        "source_rows": source_rows,
        "run_at": run_at,
        "db": db,
    }

    rule_results: list[dict[str, Any]] = []
    for rule in _get_rules_in_order():
        raw_result = rule["fn"](context)
        result = _normalize_rule_result(rule["name"], raw_result, context)
        rule_results.append(result)

        validation_result = ValidationResult(
            loan_id=result["loan_id"],
            rule_name=result["rule_name"],
            status=result["status"],
            severity=result["severity"],
            message=result["message"],
            details=result["details"],
            run_at=result["run_at"],
        )
        db.add(validation_result)
        db.flush()
        result["validation_result_id"] = validation_result.id

        if result["status"] == "fail":
            create_or_reuse_exception_for_validation_result(db, result)
        else:
            resolve_open_exceptions_for_pass_result(db, result["loan_id"], result["rule_name"], result["run_at"])

    passed = sum(1 for result in rule_results if result["status"] == "pass")
    failed = sum(1 for result in rule_results if result["status"] == "fail")

    log_audit_event(
        db,
        "validation_executed",
        loan_id=loan_id,
        actor="system",
        details={
            "loan_id": loan_id,
            "rules_executed": len(rule_results),
            "passed": passed,
            "failed": failed,
            "execution_timestamp": run_at,
        },
    )

    return rule_results


def validate_loan(loan_id: str) -> list[dict[str, Any]]:
    """Execute registered validation rules for a loan in a standalone, self-committing session."""
    db: Session = SessionLocal()
    try:
        result = _execute_validation(db, loan_id)
        db.commit()
        return result
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def validate_loan_in_session(db: Session, loan_id: str) -> list[dict[str, Any]]:
    """Execute registered validation rules for a loan using the caller's own session.

    The caller owns the transaction boundary (commit/rollback), so this can run inside
    an already-open request transaction alongside other mutations (e.g. an ingestion
    row or a reviewer field edit) instead of opening a second, independent session that
    can't see the caller's uncommitted changes.
    """
    return _execute_validation(db, loan_id)

