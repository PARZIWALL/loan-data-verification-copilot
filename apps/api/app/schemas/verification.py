"""Verification API schemas."""

from typing import Any

from pydantic import BaseModel


class VerificationRequest(BaseModel):
    loan_id: str


class BlockingException(BaseModel):
    exception_id: int
    type: str
    severity: str
    status: str


class IneligibleVerificationResponse(BaseModel):
    status: str
    loan_id: str
    reason: str
    blocking_exception_count: int
    blocking_exceptions: list[BlockingException]


class DuplicateVerificationResponse(BaseModel):
    status: str
    loan_id: str
    reason: str
    existing_verified_record_id: int
    existing_verification_timestamp: str


class VerifiedRecordResponse(BaseModel):
    status: str
    verified_record_id: int
    loan_id: str
    verified_by: str
    verification_timestamp: str
    record_hash: str | None = None
    exported: bool

