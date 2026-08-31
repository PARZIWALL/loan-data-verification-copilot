"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { api } from "@/lib/api";
import { useApiErrorHandler } from "@/lib/auth";
import type { VerifiedLoan } from "@/lib/types";
import { Badge, Button, Card, ErrorNote, Json, KeyValue, Loading } from "@/components/ui";

export default function VerifiedLoanDetailPage() {
  const params = useParams<{ verifiedLoanId: string }>();
  const verifiedLoanId = Number(params.verifiedLoanId);
  const handleError = useApiErrorHandler();

  const [record, setRecord] = useState<VerifiedLoan | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState(false);

  const load = useCallback(() => {
    api
      .verifiedLoan(verifiedLoanId)
      .then((result) => { setRecord(result); setError(null); })
      .catch((loadError) => { setError(loadError); handleError(loadError); });
  }, [verifiedLoanId, handleError]);

  useEffect(() => { load(); }, [load]);

  async function exportRecord() {
    setBusy(true);
    setError(null);
    try {
      const payload = await api.exportVerified(verifiedLoanId);
      // The API marks the record exported and returns the snapshot; hand the same
      // bytes to the user as a file so the export is genuinely a deliverable.
      const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `verified-loan-${verifiedLoanId}.json`;
      anchor.click();
      URL.revokeObjectURL(url);
      load();
    } catch (exportError) {
      setError(exportError);
      handleError(exportError);
    } finally {
      setBusy(false);
    }
  }

  if (error && !record) return <ErrorNote error={error} />;
  if (!record) return <Loading label="Loading verified record…" />;

  return (
    <div className="space-y-4">
      <div>
        <Link href="/verified-loans" className="text-xs text-slate-500 hover:text-slate-800">← Verified records</Link>
        <h1 className="mt-1 flex items-center gap-2 text-xl font-semibold text-slate-900">
          Verified record for <span className="font-mono text-base">{record.loan_id}</span>
          {record.exported && <Badge tone="resolved">exported</Badge>}
        </h1>
      </div>

      <ErrorNote error={error} />

      <div className="grid gap-4 lg:grid-cols-[1fr_1fr]">
        <Card title="Verification">
          <KeyValue
            rows={[
              ["Loan", <span key="l" className="font-mono text-xs">{record.loan_id}</span>],
              ["Verified by", record.verified_by],
              ["Verified at", record.verification_timestamp],
              ["Reviewer decision", record.reviewer_decision ?? "—"],
              ["Exported at", record.exported_at ?? "not exported"],
            ]}
          />
        </Card>

        <Card title="Integrity">
          <p className="text-sm text-slate-600">
            This snapshot is immutable. The hash covers the final data, the source reference and the
            validation summary — later changes to the live loan do not affect it.
          </p>
          <div className="mt-3 rounded border border-slate-200 bg-slate-50 p-2">
            <p className="break-all font-mono text-xs text-slate-800">{record.record_hash ?? "—"}</p>
          </div>
          <div className="mt-2 flex gap-2">
            <Button
              variant="secondary"
              onClick={() => {
                if (record.record_hash) {
                  navigator.clipboard.writeText(record.record_hash);
                  setCopied(true);
                  setTimeout(() => setCopied(false), 1500);
                }
              }}
            >
              {copied ? "Copied" : "Copy hash"}
            </Button>
            <Button onClick={exportRecord} disabled={busy}>
              {busy ? "Exporting…" : "Export JSON"}
            </Button>
          </div>
          <p className="mt-2 text-xs text-slate-500">
            Exporting is recorded in the audit trail and never recomputes the hash.
          </p>
        </Card>
      </div>

      <Card title="Final data snapshot"><Json value={record.final_data} /></Card>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Source reference"><Json value={record.source_reference} /></Card>
        <Card title="Validation summary"><Json value={record.validation_result_summary} /></Card>
      </div>

      <Card title="Audit">
        <Link href="/audit" className="text-sm text-slate-900 underline">
          View the full audit trail for {record.loan_id} →
        </Link>
      </Card>
    </div>
  );
}
