/**
 * Typed client for the loan verification API.
 *
 * One place owns the base URL, the bearer token, and error translation, so screens
 * never hand-roll fetch calls. ApiError carries the backend's `detail` string, which
 * the UI is expected to surface verbatim -- the backend's messages explain *why* an
 * action was refused (terminal exception, already dispositioned, non-editable field)
 * and rewriting them in the UI would lose that.
 */

import type {
  AIDispositionResult,
  ExceptionDetail,
  ExceptionQueueItem,
  FieldEditResult,
  LoanAuditTrail,
  LoanDetail,
  LoanListItem,
  LoginResponse,
  Paginated,
  RevalidateResult,
  ReviewerDecisionResult,
  SourceType,
  Summary,
  User,
  VerifiedLoan,
  VerifyResult,
} from "./types";

const BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
const TOKEN_KEY = "ldvc.token";
const USER_KEY = "ldvc.user";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
    this.name = "ApiError";
  }
  get isUnauthorized() {
    return this.status === 401;
  }
  get isForbidden() {
    return this.status === 403;
  }
  get isConflict() {
    return this.status === 409;
  }
}

export const tokenStore = {
  get(): string | null {
    if (typeof window === "undefined") return null;
    return window.localStorage.getItem(TOKEN_KEY);
  },
  set(token: string, user: User) {
    window.localStorage.setItem(TOKEN_KEY, token);
    window.localStorage.setItem(USER_KEY, JSON.stringify(user));
  },
  getUser(): User | null {
    if (typeof window === "undefined") return null;
    const raw = window.localStorage.getItem(USER_KEY);
    try {
      return raw ? (JSON.parse(raw) as User) : null;
    } catch {
      return null;
    }
  },
  clear() {
    window.localStorage.removeItem(TOKEN_KEY);
    window.localStorage.removeItem(USER_KEY);
  },
};

async function toApiError(response: Response): Promise<ApiError> {
  let detail = response.statusText || `Request failed (${response.status})`;
  try {
    const body = await response.json();
    if (typeof body?.detail === "string") {
      detail = body.detail;
    } else if (body?.detail) {
      // Verification conflicts return a structured detail object.
      detail = body.detail.reason ?? JSON.stringify(body.detail);
    }
  } catch {
    /* non-JSON error body; keep the status text */
  }
  return new ApiError(response.status, detail);
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = tokenStore.get();
  const headers = new Headers(init.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (init.body && !(init.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }

  let response: Response;
  try {
    response = await fetch(`${BASE_URL}${path}`, { ...init, headers });
  } catch {
    throw new ApiError(0, `Cannot reach the API at ${BASE_URL}. Is the backend running?`);
  }

  if (!response.ok) throw await toApiError(response);
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

function query(params: Record<string, string | number | boolean | undefined | null>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== "") search.set(key, String(value));
  }
  const qs = search.toString();
  return qs ? `?${qs}` : "";
}

export const api = {
  /* auth */
  login: (username: string, password: string) =>
    request<LoginResponse>("/auth/login", {
      method: "POST",
      body: JSON.stringify({ username, password }),
    }),
  me: () => request<User>("/auth/me"),

  /* dashboard */
  summary: () => request<Summary>("/summary"),

  /* ingestion */
  upload: (file: File, sourceType: SourceType) => {
    const form = new FormData();
    form.append("file", file);
    form.append("source_type", sourceType);
    return request<import("./types").UploadResult>("/upload", { method: "POST", body: form });
  },

  /* loans */
  listLoans: (params: {
    search?: string;
    payment_status?: string;
    has_open_exceptions?: boolean;
    verified?: boolean;
    page?: number;
    page_size?: number;
  } = {}) => request<Paginated<LoanListItem>>(`/loans${query(params)}`),
  loan: (loanId: string) => request<LoanDetail>(`/loans/${encodeURIComponent(loanId)}`),
  revalidate: (loanId: string) =>
    request<RevalidateResult>(`/loans/${encodeURIComponent(loanId)}/revalidate`, { method: "POST" }),

  /* exceptions */
  listExceptions: (params: {
    type?: string;
    severity?: string;
    status?: string;
    search?: string;
    page?: number;
    page_size?: number;
  } = {}) => request<Paginated<ExceptionQueueItem>>(`/exceptions${query(params)}`),
  exception: (exceptionId: number) => request<ExceptionDetail>(`/exceptions/${exceptionId}`),
  comment: (exceptionId: number, text: string) =>
    request(`/exceptions/${exceptionId}/comment`, { method: "POST", body: JSON.stringify({ text }) }),
  editField: (exceptionId: number, field: string, value: unknown) =>
    request<FieldEditResult>(`/exceptions/${exceptionId}/edit`, {
      method: "POST",
      body: JSON.stringify({ field, value }),
    }),
  decide: (
    exceptionId: number,
    decision: "approve" | "reject" | "request-correction",
    comment?: string,
  ) =>
    request<ReviewerDecisionResult>(`/exceptions/${exceptionId}/${decision}`, {
      method: "POST",
      body: JSON.stringify({ comment: comment ?? null }),
    }),

  /* AI copilot */
  generateRecommendation: (exceptionId: number) =>
    request<Record<string, unknown>>(`/exceptions/${exceptionId}/ai-recommendation`, { method: "POST" }),
  acceptRecommendation: (id: number, comment?: string) =>
    request<AIDispositionResult>(`/ai-recommendations/${id}/accept`, {
      method: "POST",
      body: JSON.stringify({ comment: comment ?? null }),
    }),
  editRecommendation: (id: number, corrections: { field: string; value: unknown }[], comment?: string) =>
    request<AIDispositionResult>(`/ai-recommendations/${id}/edit`, {
      method: "POST",
      body: JSON.stringify({ corrections, comment: comment ?? null }),
    }),
  rejectRecommendation: (id: number, comment?: string) =>
    request<AIDispositionResult>(`/ai-recommendations/${id}/reject`, {
      method: "POST",
      body: JSON.stringify({ comment: comment ?? null }),
    }),

  /* verification */
  verify: (loanId: string) =>
    request<VerifyResult>("/verified-loans", { method: "POST", body: JSON.stringify({ loan_id: loanId }) }),
  listVerified: (params: { page?: number; page_size?: number } = {}) =>
    request<Paginated<VerifiedLoan>>(`/verified-loans${query(params)}`),
  verifiedLoan: (id: number) => request<VerifiedLoan>(`/verified-loans/${id}`),
  exportVerified: (id: number) =>
    request<Record<string, unknown>>(`/verified-loans/${id}/export`, { method: "POST" }),

  /* audit */
  auditTrail: (loanId: string, params: { page?: number; page_size?: number } = {}) =>
    request<LoanAuditTrail>(`/audit/${encodeURIComponent(loanId)}${query(params)}`),
};
