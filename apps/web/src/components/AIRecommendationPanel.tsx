"use client";

/**
 * The AI copilot panel.
 *
 * Two things this component must never blur:
 *  - the recommendation is advisory; it is visually separated from the human decision
 *  - accepting a request_human_review recommendation does NOT resolve the exception,
 *    it only records that the reviewer agrees the AI was right to decline
 */

import { useState } from "react";
import { api } from "@/lib/api";
import type { AIRecommendation, SuggestedCorrection } from "@/lib/types";
import { Badge, Button, Card, ErrorNote, StatusBadge } from "@/components/ui";

function confidenceBand(value: number): string {
  if (value >= 0.9) return "strong evidence";
  if (value >= 0.7) return "good evidence, minor uncertainty";
  if (value >= 0.4) return "mixed or incomplete evidence";
  return "weak evidence";
}

const TYPE_LABELS: Record<string, string> = {
  suggest_field_correction: "Suggests a correction",
  suggest_no_change: "Suggests no change",
  request_human_review: "Requests human review",
};

function CorrectionDiff({ correction }: { correction: SuggestedCorrection }) {
  return (
    <div className="flex flex-wrap items-center gap-2 rounded border border-slate-200 bg-slate-50 px-2.5 py-1.5 text-sm">
      <span className="font-mono text-xs text-slate-600">{correction.field}</span>
      <span className="tabular-nums text-slate-500 line-through">{String(correction.current_value ?? "—")}</span>
      <span className="text-slate-400">→</span>
      <span className="tabular-nums font-medium text-slate-900">{String(correction.suggested_value ?? "—")}</span>
    </div>
  );
}

export function AIRecommendationPanel({
  exceptionId,
  recommendations,
  canAct,
  onChanged,
}: {
  exceptionId: number;
  recommendations: AIRecommendation[];
  canAct: boolean;
  onChanged: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [comment, setComment] = useState("");
  const [editValues, setEditValues] = useState<Record<string, string>>({});

  async function run(action: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await action();
      setComment("");
      setEditValues({});
      onChanged();
    } catch (actionError) {
      setError(actionError);
    } finally {
      setBusy(false);
    }
  }

  if (recommendations.length === 0) {
    return (
      <Card title="AI copilot">
        <p className="text-sm text-slate-600">
          No recommendation yet. The copilot reads only the stored evidence for this exception —
          canonical values, source records and validation history — and proposes an action for you
          to accept, edit or reject.
        </p>
        <ErrorNote error={error} />
        {canAct ? (
          <Button
            className="mt-3"
            disabled={busy}
            onClick={() => run(() => api.generateRecommendation(exceptionId))}
          >
            {busy ? "Analyzing evidence…" : "Generate AI recommendation"}
          </Button>
        ) : (
          <p className="mt-3 text-xs text-slate-500">Only reviewers can generate recommendations.</p>
        )}
      </Card>
    );
  }

  return (
    <div className="space-y-4">
      {recommendations.map((recommendation) => {
        const pending = recommendation.reviewer_status === "pending";
        const corrections = recommendation.suggested_corrections;
        return (
          <Card
            key={recommendation.ai_recommendation_id}
            title={
              <span className="flex items-center gap-2">
                AI copilot
                <Badge tone="neutral">advisory</Badge>
                <StatusBadge status={recommendation.reviewer_status} />
              </span>
            }
          >
            <div className="space-y-3">
              <div className="flex flex-wrap items-center gap-2">
                <Badge tone="neutral">
                  {TYPE_LABELS[recommendation.recommendation_type ?? ""] ?? recommendation.recommendation_type}
                </Badge>
                {recommendation.confidence !== null && (
                  <span className="text-xs text-slate-500">
                    confidence {(recommendation.confidence * 100).toFixed(0)}% — {confidenceBand(recommendation.confidence)}
                  </span>
                )}
              </div>

              {recommendation.confidence !== null && (
                <div className="h-1.5 overflow-hidden rounded bg-slate-100">
                  <div className="h-full bg-slate-700" style={{ width: `${recommendation.confidence * 100}%` }} />
                </div>
              )}

              {recommendation.downgraded && (
                <div className="rounded border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900">
                  <p className="font-medium">This recommendation was downgraded by the system.</p>
                  <p className="text-xs">It was not fully supported by the evidence in the packet.</p>
                  {recommendation.downgrade_reasons.length > 0 && (
                    <ul className="mt-1 list-disc pl-4 text-xs">
                      {recommendation.downgrade_reasons.map((reason, index) => <li key={index}>{reason}</li>)}
                    </ul>
                  )}
                </div>
              )}

              {recommendation.summary && <p className="text-sm font-medium text-slate-900">{recommendation.summary}</p>}
              {recommendation.explanation && <p className="text-sm text-slate-700">{recommendation.explanation}</p>}

              {corrections.length > 0 && (
                <div className="space-y-1.5">
                  <p className="text-xs font-medium text-slate-600">Proposed change</p>
                  {corrections.map((correction, index) => <CorrectionDiff key={index} correction={correction} />)}
                </div>
              )}

              {recommendation.evidence_citations.length > 0 && (
                <div>
                  <p className="text-xs font-medium text-slate-600">Cited evidence</p>
                  <ul className="mt-1 space-y-0.5 text-xs text-slate-600">
                    {recommendation.evidence_citations.map((citation, index) => (
                      <li key={index} className="font-mono">
                        {citation.source_file ?? "canonical"}
                        {citation.source_row_number !== null ? ` row ${citation.source_row_number}` : ""}
                        {citation.field ? ` · ${citation.field}` : ""}
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {recommendation.limitations.length > 0 && (
                <div>
                  <p className="text-xs font-medium text-slate-600">Limitations</p>
                  <ul className="mt-1 list-disc pl-4 text-xs text-slate-600">
                    {recommendation.limitations.map((limitation, index) => <li key={index}>{limitation}</li>)}
                  </ul>
                </div>
              )}

              <p className="text-xs text-slate-400">
                {recommendation.model_name} · prompt {recommendation.prompt_version} · {recommendation.created_at}
              </p>

              {recommendation.recommendation_type === "request_human_review" && pending && (
                <p className="rounded border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-600">
                  Accepting records that you agree the copilot was right not to propose a change. It does
                  not resolve this exception — that decision stays with you.
                </p>
              )}

              <ErrorNote error={error} />

              {pending && canAct ? (
                <div className="space-y-3 border-t border-slate-200 pt-3">
                  <div>
                    <label className="block text-xs font-medium text-slate-600">Comment (optional)</label>
                    <input
                      value={comment}
                      onChange={(event) => setComment(event.target.value)}
                      className="mt-1 w-full rounded border border-slate-300 px-3 py-1.5 text-sm"
                      placeholder="Why you are accepting, editing or rejecting"
                    />
                  </div>

                  {corrections.length > 0 && (
                    <div className="space-y-1.5">
                      <p className="text-xs font-medium text-slate-600">Or apply your own values instead</p>
                      {corrections.map((correction) => (
                        <div key={correction.field} className="flex items-center gap-2">
                          <span className="w-40 font-mono text-xs text-slate-600">{correction.field}</span>
                          <input
                            value={editValues[correction.field] ?? String(correction.suggested_value ?? "")}
                            onChange={(event) =>
                              setEditValues((current) => ({ ...current, [correction.field]: event.target.value }))
                            }
                            className="flex-1 rounded border border-slate-300 px-2 py-1 text-sm"
                          />
                        </div>
                      ))}
                    </div>
                  )}

                  <div className="flex flex-wrap gap-2">
                    <Button
                      disabled={busy}
                      onClick={() => run(() => api.acceptRecommendation(recommendation.ai_recommendation_id, comment || undefined))}
                    >
                      {busy ? "Working…" : corrections.length > 0 ? "Accept and apply" : "Accept"}
                    </Button>
                    {corrections.length > 0 && (
                      <Button
                        variant="secondary"
                        disabled={busy}
                        onClick={() =>
                          run(() =>
                            api.editRecommendation(
                              recommendation.ai_recommendation_id,
                              corrections.map((correction) => ({
                                field: correction.field,
                                value: editValues[correction.field] ?? correction.suggested_value,
                              })),
                              comment || undefined,
                            ),
                          )
                        }
                      >
                        Apply my values
                      </Button>
                    )}
                    <Button
                      variant="danger"
                      disabled={busy}
                      onClick={() => run(() => api.rejectRecommendation(recommendation.ai_recommendation_id, comment || undefined))}
                    >
                      Reject
                    </Button>
                  </div>
                </div>
              ) : (
                <p className="border-t border-slate-200 pt-3 text-xs text-slate-500">
                  {pending
                    ? "Only reviewers can act on recommendations."
                    : `Already ${recommendation.reviewer_status} by a reviewer.`}
                </p>
              )}
            </div>
          </Card>
        );
      })}
    </div>
  );
}
