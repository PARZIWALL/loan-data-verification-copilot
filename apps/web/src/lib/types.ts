/**
 * API types mirrored from the FastAPI backend.
 *
 * These match the real response shapes exactly -- keep them in sync with
 * apps/api/app/schemas/. Where the backend can return one of several shapes for the
 * same endpoint (verification), that is modelled as a discriminated union so callers
 * are forced to handle each outcome.
 */

export type Role = "data_operator" | "reviewer" | "data_consumer";
export type Severity = "critical" | "high" | "medium" | "low";
export type ExceptionStatus = "open" | "in_review" | "resolved" | "rejected";
export type ReviewerStatus = "pending" | "accepted" | "edited" | "rejected";
export type RecommendationType =
  | "suggest_field_correction"
  | "suggest_no_change"
  | "request_human_review";
export type SourceType = "loan_tape" | "servicer_update" | "document_manifest";

export interface User {
  id: number;
  username: string;
  role: Role;
}

export interface LoginResponse {
  access_token: string;
  token_type: string;
  user: User;
}

/* ---------------------------------------------------------------- ingestion */

export interface FailedRow {
  row_number: number;
  reason: string;
}

export interface UploadResult {
  source_type: SourceType;
  total_rows: number;
  imported_rows: number;
  failed_rows: number;
  failed_details: FailedRow[];
}

/* -------------------------------------------------------------------- loans */

export interface LoanListItem {
  loan_id: string;
  borrower_id: string | null;
  loan_type: string | null;
  original_principal: number | null;
  current_balance: number | null;
  interest_rate: number | null;
  borrower_state: string | null;
  payment_status: string | null;
  document_status: string | null;
  last_updated_at: string | null;
  open_exception_count: number;
  verified: boolean;
}

export interface Paginated<T> {
  items: T[];
  page: number;
  page_size: number;
  total: number;
  total_pages: number;
}

export interface ValidationResultItem {
  id?: number;
  rule_name: string;
  status: string | null;
  severity: string | null;
  message: string | null;
  details: Record<string, unknown> | null;
  run_at: string | null;
}

export interface LoanSourceRecord {
  id: number;
  source_file: string | null;
  source_system: string | null;
  source_row_number: number | null;
  raw_data: Record<string, unknown> | null;
  imported_at: string | null;
  import_status: string | null;
}

export interface CanonicalLoan {
  loan_id: string | null;
  borrower_id: string | null;
  loan_type: string | null;
  origination_date: string | null;
  maturity_date: string | null;
  original_principal: number | null;
  current_balance: number | null;
  interest_rate: number | null;
  term_months: number | null;
  borrower_state: string | null;
  loan_purpose: string | null;
  credit_grade: string | null;
  employment_length: string | null;
  income_band: string | null;
  payment_status: string | null;
  days_past_due: number | null;
  servicer_name: string | null;
  last_payment_date: string | null;
  last_updated_at: string | null;
  document_status: string | null;
  source_system: string | null;
  primary_source_id: number | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface LoanDetail extends CanonicalLoan {
  loan_id: string;
  validation_results: ValidationResultItem[];
  exceptions: {
    id: number;
    type: string;
    severity: string;
    status: string;
    created_at: string;
    resolved_at: string | null;
  }[];
  source_records: LoanSourceRecord[];
}

export interface RevalidateResult {
  loan_id: string;
  rules_executed: number;
  passed: number;
  failed: number;
}

/* --------------------------------------------------------------- exceptions */

export interface ExceptionQueueItem {
  exception_id: number;
  loan_id: string;
  borrower_id: string | null;
  type: string;
  severity: Severity;
  status: ExceptionStatus;
  validation_result_id: number | null;
  message: string | null;
  created_at: string;
  resolved_at: string | null;
}

export interface SuggestedCorrection {
  field: string;
  current_value: string | number | boolean | null;
  suggested_value: string | number | boolean | null;
}

export interface EvidenceCitation {
  source_id: number | null;
  source_file: string | null;
  source_row_number: number | null;
  field: string | null;
}

export interface AIRecommendation {
  ai_recommendation_id: number;
  exception_id: number | null;
  loan_id: string;
  recommendation_type: RecommendationType | null;
  summary: string | null;
  explanation: string | null;
  confidence: number | null;
  affected_fields: string[];
  suggested_corrections: SuggestedCorrection[];
  evidence_citations: EvidenceCitation[];
  limitations: string[];
  severity_classification: string | null;
  model_name: string | null;
  prompt_version: string | null;
  downgraded: boolean;
  downgrade_reasons: string[];
  reviewer_status: ReviewerStatus;
  created_at: string;
}

export type ReviewActionType =
  | "comment"
  | "edit_field"
  | "approve"
  | "reject"
  | "request_correction"
  | "ai_accept"
  | "ai_edit"
  | "ai_reject";

export interface ReviewAction {
  action_id: number;
  action_type: ReviewActionType;
  reviewer_id: number | null;
  field_name: string | null;
  old_value: unknown;
  new_value: unknown;
  comment_text: string | null;
  ai_recommendation_id: number | null;
  created_at: string;
}

export interface AuditEvent {
  id: number;
  event_type: string;
  actor: string | null;
  created_at: string;
  details: Record<string, unknown> | null;
}

export interface ExceptionDetail {
  exception: {
    id: number;
    loan_id: string;
    type: string;
    severity: Severity;
    status: ExceptionStatus;
    created_at: string;
    resolved_at: string | null;
  };
  validation_result: ValidationResultItem;
  canonical_loan: CanonicalLoan;
  source_evidence: LoanSourceRecord[];
  historical_validation_results: ValidationResultItem[];
  audit_events: AuditEvent[];
  review_actions: ReviewAction[];
  ai_recommendations: AIRecommendation[];
}

export interface FieldEditResult {
  status: "updated" | "no_change";
  message: string;
  exception_id: number | null;
  loan_id: string | null;
  reviewer_id: number | null;
  action_id: number | null;
  field_name: string | null;
  old_value: unknown;
  new_value: unknown;
  created_at: string | null;
}

export interface ReviewerDecisionResult {
  action_id: number;
  exception_id: number;
  loan_id: string;
  reviewer_id: number;
  action_type: string;
  comment_text: string | null;
  created_at: string;
  exception_status: ExceptionStatus;
}

export interface AppliedChange {
  field: string | null;
  old_value: unknown;
  new_value: unknown;
  status: string | null;
  review_action_id: number | null;
}

export interface AIDispositionResult {
  ai_recommendation_id: number;
  exception_id: number | null;
  loan_id: string;
  disposition: "accepted" | "edited" | "rejected";
  reviewer_status: ReviewerStatus;
  recommendation_type: RecommendationType | null;
  reviewer_id: number;
  review_action_id: number;
  comment_text: string | null;
  applied_changes: AppliedChange[];
  created_at: string;
}

/* -------------------------------------------------------------- verification */

export interface VerifiedLoan {
  verified_loan_id: number;
  loan_id: string;
  final_data: Record<string, unknown> | null;
  source_reference: Record<string, unknown> | null;
  validation_result_summary: Record<string, unknown> | null;
  reviewer_decision: string | null;
  verified_by: string | null;
  verification_timestamp: string | null;
  record_hash: string | null;
  exported: boolean;
  exported_at: string | null;
}

/**
 * POST /verified-loans returns 200 for both success and ineligibility -- an
 * ineligible loan is a normal workflow outcome, not an error. 409 means already
 * verified and surfaces as an ApiError.
 */
export type VerifyResult =
  | {
      status: "verified";
      verified_record_id: number;
      loan_id: string;
      verified_by: string;
      verification_timestamp: string;
      record_hash: string | null;
      exported: boolean;
    }
  | {
      status: "ineligible";
      loan_id: string;
      reason: string;
      blocking_exception_count: number;
      blocking_exceptions: {
        exception_id: number;
        type: string;
        severity: string;
        status: string;
      }[];
    };

/* ------------------------------------------------------------------ summary */

export interface Summary {
  loans: { total: number; verified: number; with_open_exceptions: number; clean: number };
  exceptions: {
    total: number;
    open: number;
    in_review: number;
    resolved: number;
    rejected: number;
    by_severity: Record<Severity, number>;
    by_type: { type: string; count: number }[];
  };
  validation: { total_results: number; passed: number; failed: number; latest_run_at: string | null };
  ingestion: { files: number; source_rows: number; rows_imported: number; rows_failed: number };
  ai: { recommendations: number; pending: number; accepted: number; edited: number; rejected: number };
  verification: { verified_records: number; exported: number };
  audit: { events: number };
  data_quality_score: number;
}

export interface LoanAuditTrail {
  loan_id: string;
  items: AuditEvent[];
  page: number;
  page_size: number;
  total: number;
  total_pages: number;
}
