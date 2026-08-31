"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { ApiError, api } from "@/lib/api";
import { useApiErrorHandler, useAuth } from "@/lib/auth";
import type { ExceptionDetail, VerifyResult } from "@/lib/types";
import { AIRecommendationPanel } from "@/components/AIRecommendationPanel";
import { SourceComparison } from "@/components/SourceComparison";
import {
  Badge, Button, Card, Empty, ErrorNote, Json, KeyValue, Loading, SeverityBadge, StatusBadge, Table,
} from "@/components/ui";

const TERMINAL: string[] = ["resolved", "rejected"];

export default function ExceptionDetailPage() {
  const params = useParams<{ exceptionId: string }>();
  const exceptionId = Number(params.exceptionId);
  const { user } = useAuth();
  const handleError = useApiErrorHandler();
  const isReviewer = user?.role === "reviewer";

  const [detail, setDetail] = useState<ExceptionDetail | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [actionError, setActionError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const [comment, setComment] = useState("");
  const [editField, setEditField] = useState("");
  const [editValue, setEditValue] = useState("");
  const [verifyResult, setVerifyResult] = useState<VerifyResult | null>(null);

  const load = useCallback(() => {
    api
      .exception(exceptionId)
      .then((result) => { setDetail(result); setError(null); })
      .catch((loadError) => { setError(loadError); handleError(loadError); });
  }, [exceptionId, handleError]);

  useEffect(() => { load(); }, [load]);

  async function run(action: () => Promise<unknown>) {
    setBusy(true);
    setActionError(null);
    try {
      await action();
      setComment("");
      setEditField("");
      setEditValue("");
      load();
    } catch (runError) {
      setActionError(runError);
      handleError(runError);
    } finally {
      setBusy(false);
    }
  }

  if (error) return <ErrorNote error={error} />;
  if (!detail) return <Loading label="Loading exception…" />;

  const { exception, validation_result, canonical_loan, source_evidence } = detail;
  const isTerminal = TERMINAL.includes(exception.status);

  // Fields worth comparing: whatever the failing rule reported, plus the fields the AI
  // flagged. Falls back to the common conflict fields.
  const detailKeys = Object.keys(validation_result.details ?? {});
  const aiFields = detail.ai_recommendations.flatMap((rec) => rec.affected_fields);
  const focusFields = Array.from(
    new Set([
      ...detailKeys.filter((key) => key in (canonical_loan as unknown as Record<string, unknown>)),
      ...aiFields,
      "current_balance", "original_principal", "payment_status", "days_past_due", "document_status", "borrower_state",
    ]),
  );

  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between gap-4">
        <div>
          <Link href="/exceptions" className="text-xs text-slate-500 hover:text-slate-800">← Exception queue</Link>
          <h1 className="mt-1 flex items-center gap-2 text-xl font-semibold text-slate-900">
            <span className="font-mono text-base">{exception.type}</span>
            <SeverityBadge severity={exception.severity} />
            <StatusBadge status={exception.status} />
          </h1>
          <p className="text-sm text-slate-600">
            Loan <Link href={`/loans/${exception.loan_id}`} className="font-mono underline">{exception.loan_id}</Link>
            {canonical_loan.borrower_id && <> · borrower <span className="font-mono">{canonical_loan.borrower_id}</span></>}
            {" · raised "}{exception.created_at}
            {exception.resolved_at && ` · closed ${exception.resolved_at}`}
          </p>
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-[1.4fr_1fr]">
        {/* ------------------------------------------------ evidence column */}
        <div className="space-y-4">
          <Card title="Why this failed">
            <KeyValue
              rows={[
                ["Rule", <span key="r" className="font-mono text-xs">{validation_result.rule_name}</span>],
                ["Message", validation_result.message],
                ["Severity", validation_result.severity],
                ["Checked at", validation_result.run_at],
              ]}
            />
            {validation_result.details && (
              <div className="mt-3">
                <p className="mb-1 text-xs font-medium text-slate-600">Rule details</p>
                <Json value={validation_result.details} />
              </div>
            )}
          </Card>

          <SourceComparison
            canonicalLoan={canonical_loan}
            sourceEvidence={source_evidence}
            focusFields={focusFields}
          />

          <Card title="Validation history">
            {detail.historical_validation_results.length === 0 ? (
              <Empty>No prior runs.</Empty>
            ) : (
              <Table head={["Checked at", "Status", "Message"]}>
                {detail.historical_validation_results.map((result, index) => (
                  <tr key={index} className="border-b border-slate-100">
                    <td className="px-3 py-1.5 text-xs text-slate-500">{result.run_at}</td>
                    <td className="px-3 py-1.5">
                      <Badge tone={result.status === "pass" ? "resolved" : "open"}>{result.status}</Badge>
                    </td>
                    <td className="px-3 py-1.5 text-slate-700">{result.message}</td>
                  </tr>
                ))}
              </Table>
            )}
          </Card>

          <Card title="Review & action history">
            {detail.review_actions.length === 0 ? (
              <Empty>No actions taken yet.</Empty>
            ) : (
              <Table head={["When", "Action", "Detail", "Source"]}>
                {detail.review_actions.map((action) => (
                  <tr key={action.action_id} className="border-b border-slate-100">
                    <td className="px-3 py-1.5 text-xs text-slate-500">{action.created_at}</td>
                    <td className="px-3 py-1.5"><Badge tone="neutral">{action.action_type.replace(/_/g, " ")}</Badge></td>
                    <td className="px-3 py-1.5 text-slate-700">
                      {action.field_name ? (
                        <span className="text-xs">
                          <span className="font-mono">{action.field_name}</span>{" "}
                          <span className="line-through text-slate-400">{String(action.old_value ?? "—")}</span>{" → "}
                          <span className="font-medium">{String(action.new_value ?? "—")}</span>
                        </span>
                      ) : (
                        action.comment_text ?? <span className="text-slate-400">—</span>
                      )}
                    </td>
                    <td className="px-3 py-1.5">
                      {action.ai_recommendation_id ? (
                        <Badge tone="accepted">AI-assisted</Badge>
                      ) : (
                        <span className="text-xs text-slate-400">reviewer</span>
                      )}
                    </td>
                  </tr>
                ))}
              </Table>
            )}
          </Card>

          <Card title="Audit trail">
            {detail.audit_events.length === 0 ? (
              <Empty>No audit events.</Empty>
            ) : (
              <ol className="space-y-1.5">
                {detail.audit_events.map((event) => (
                  <li key={event.id} className="flex items-baseline gap-2 text-xs">
                    <span className="w-40 shrink-0 text-slate-400">{event.created_at}</span>
                    <Badge tone="neutral">{event.actor ?? "system"}</Badge>
                    <span className="font-mono text-slate-700">{event.event_type}</span>
                  </li>
                ))}
              </ol>
            )}
          </Card>
        </div>

        {/* -------------------------------------------------- action column */}
        <div className="space-y-4">
          <AIRecommendationPanel
            exceptionId={exceptionId}
            recommendations={detail.ai_recommendations}
            canAct={isReviewer && !isTerminal}
            onChanged={load}
          />

          <Card title="Reviewer decision">
            {!isReviewer ? (
              <p className="text-sm text-slate-500">Only reviewers can act on exceptions.</p>
            ) : (
              <div className="space-y-3">
                <ErrorNote error={actionError} />

                {isTerminal && (
                  <p className="rounded border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-600">
                    This exception is {exception.status} and can no longer be decided.
                  </p>
                )}

                <div>
                  <label className="block text-xs font-medium text-slate-600">Comment</label>
                  <textarea
                    value={comment}
                    onChange={(event) => setComment(event.target.value)}
                    rows={2}
                    maxLength={2000}
                    className="mt-1 w-full rounded border border-slate-300 px-3 py-1.5 text-sm"
                  />
                  <Button
                    variant="secondary"
                    className="mt-1.5"
                    disabled={busy || !comment.trim()}
                    onClick={() => run(() => api.comment(exceptionId, comment.trim()))}
                  >
                    Add comment
                  </Button>
                </div>

                <div className="border-t border-slate-200 pt-3">
                  <p className="text-xs font-medium text-slate-600">Correct a field</p>
                  <div className="mt-1 flex gap-2">
                    <input
                      value={editField}
                      onChange={(event) => setEditField(event.target.value)}
                      placeholder="field"
                      className="w-40 rounded border border-slate-300 px-2 py-1 text-sm font-mono"
                    />
                    <input
                      value={editValue}
                      onChange={(event) => setEditValue(event.target.value)}
                      placeholder="new value"
                      className="flex-1 rounded border border-slate-300 px-2 py-1 text-sm"
                    />
                  </div>
                  <Button
                    variant="secondary"
                    className="mt-1.5"
                    disabled={busy || !editField.trim() || isTerminal}
                    onClick={() => run(() => api.editField(exceptionId, editField.trim(), editValue))}
                  >
                    Apply edit and revalidate
                  </Button>
                </div>

                <div className="flex flex-wrap gap-2 border-t border-slate-200 pt-3">
                  <Button disabled={busy || isTerminal} onClick={() => run(() => api.decide(exceptionId, "approve", comment || undefined))}>
                    Approve
                  </Button>
                  <Button variant="danger" disabled={busy || isTerminal} onClick={() => run(() => api.decide(exceptionId, "reject", comment || undefined))}>
                    Reject
                  </Button>
                  <Button variant="secondary" disabled={busy || isTerminal} onClick={() => run(() => api.decide(exceptionId, "request-correction", comment || undefined))}>
                    Request correction
                  </Button>
                </div>
              </div>
            )}
          </Card>

          {isReviewer && (
            <Card title="Verification">
              <p className="text-sm text-slate-600">
                A loan can only be verified once every exception on it is resolved.
              </p>
              <Button
                className="mt-2"
                variant="secondary"
                disabled={busy}
                onClick={() =>
                  run(async () => {
                    const result = await api.verify(exception.loan_id);
                    setVerifyResult(result);
                  })
                }
              >
                Verify this loan
              </Button>

              {verifyResult?.status === "verified" && (
                <div className="mt-3 rounded border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-900">
                  <p className="font-medium">Verified.</p>
                  <p className="mt-1 break-all font-mono text-xs">{verifyResult.record_hash}</p>
                  <Link href={`/verified-loans/${verifyResult.verified_record_id}`} className="mt-1 inline-block text-xs underline">
                    Open verified record →
                  </Link>
                </div>
              )}
              {verifyResult?.status === "ineligible" && (
                <div className="mt-3 rounded border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900">
                  <p className="font-medium">Not eligible: {verifyResult.reason}</p>
                  <ul className="mt-1 space-y-0.5 text-xs">
                    {verifyResult.blocking_exceptions.map((blocker) => (
                      <li key={blocker.exception_id}>
                        <Link href={`/exceptions/${blocker.exception_id}`} className="font-mono underline">
                          {blocker.type}
                        </Link>{" "}
                        ({blocker.status})
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              {actionError instanceof ApiError && actionError.isConflict && (
                <p className="mt-2 text-xs text-slate-600">This loan is already verified.</p>
              )}
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}
