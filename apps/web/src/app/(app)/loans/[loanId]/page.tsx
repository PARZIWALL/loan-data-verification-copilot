"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { api } from "@/lib/api";
import { useApiErrorHandler, useAuth } from "@/lib/auth";
import type { LoanDetail } from "@/lib/types";
import {
  Badge, Button, Card, Empty, ErrorNote, Json, KeyValue, Loading, Money, Table,
} from "@/components/ui";

export default function LoanDetailPage() {
  const params = useParams<{ loanId: string }>();
  const loanId = decodeURIComponent(params.loanId);
  const { user } = useAuth();
  const handleError = useApiErrorHandler();

  const [loan, setLoan] = useState<LoanDetail | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const [expandedSource, setExpandedSource] = useState<number | null>(null);

  const load = useCallback(() => {
    api
      .loan(loanId)
      .then((result) => { setLoan(result); setError(null); })
      .catch((loadError) => { setError(loadError); handleError(loadError); });
  }, [loanId, handleError]);

  useEffect(() => { load(); }, [load]);

  async function revalidate() {
    setBusy(true);
    setError(null);
    try {
      await api.revalidate(loanId);
      load();
    } catch (revalidateError) {
      setError(revalidateError);
      handleError(revalidateError);
    } finally {
      setBusy(false);
    }
  }

  if (error && !loan) return <ErrorNote error={error} />;
  if (!loan) return <Loading label="Loading loan…" />;

  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between gap-4">
        <div>
          <Link href="/loans" className="text-xs text-slate-500 hover:text-slate-800">← Loans</Link>
          <h1 className="mt-1 text-xl font-semibold text-slate-900">
            Loan <span className="font-mono text-base">{loan.loan_id}</span>
          </h1>
          <p className="text-sm text-slate-600">Borrower <span className="font-mono">{loan.borrower_id ?? "—"}</span></p>
        </div>
        <Button variant="secondary" onClick={revalidate} disabled={busy}>
          {busy ? "Re-validating…" : "Re-validate"}
        </Button>
      </div>

      <ErrorNote error={error} />

      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Canonical record">
          <KeyValue
            rows={[
              ["Principal", <Money key="p" value={loan.original_principal} />],
              ["Current balance", <Money key="b" value={loan.current_balance} />],
              ["Interest rate", loan.interest_rate !== null ? `${(loan.interest_rate * 100).toFixed(3)}%` : null],
              ["Term (months)", loan.term_months],
              ["Origination", loan.origination_date],
              ["Maturity", loan.maturity_date],
              ["State", loan.borrower_state],
              ["Payment status", loan.payment_status],
              ["Days past due", loan.days_past_due],
              ["Document status", loan.document_status],
              ["Servicer", loan.servicer_name],
              ["Last updated", loan.last_updated_at],
            ]}
          />
        </Card>

        <Card title="Exceptions">
          {loan.exceptions.length === 0 ? (
            <Empty>No exceptions on this loan.</Empty>
          ) : (
            <Table head={["Type", "Severity", "Status", ""]}>
              {loan.exceptions.map((exception) => (
                <tr key={exception.id} className="border-b border-slate-100">
                  <td className="px-3 py-1.5 font-mono text-xs">{exception.type}</td>
                  <td className="px-3 py-1.5"><Badge tone={exception.severity}>{exception.severity}</Badge></td>
                  <td className="px-3 py-1.5"><Badge tone={exception.status}>{exception.status.replace("_", " ")}</Badge></td>
                  <td className="px-3 py-1.5 text-right">
                    {user?.role === "reviewer" && (
                      <Link href={`/exceptions/${exception.id}`} className="text-xs font-medium text-slate-900 underline">
                        Review
                      </Link>
                    )}
                  </td>
                </tr>
              ))}
            </Table>
          )}
        </Card>
      </div>

      <Card title="Validation results">
        {loan.validation_results.length === 0 ? (
          <Empty>This loan has not been validated yet.</Empty>
        ) : (
          <Table head={["Rule", "Status", "Severity", "Message", "Checked at"]}>
            {loan.validation_results.map((result, index) => (
              <tr key={index} className="border-b border-slate-100">
                <td className="px-3 py-1.5 font-mono text-xs">{result.rule_name}</td>
                <td className="px-3 py-1.5">
                  <Badge tone={result.status === "pass" ? "resolved" : "open"}>{result.status}</Badge>
                </td>
                <td className="px-3 py-1.5 text-xs">{result.severity}</td>
                <td className="px-3 py-1.5 text-slate-700">{result.message}</td>
                <td className="px-3 py-1.5 text-xs text-slate-500">{result.run_at}</td>
              </tr>
            ))}
          </Table>
        )}
      </Card>

      <Card title="Source lineage">
        {loan.source_records.length === 0 ? (
          <Empty>No source records.</Empty>
        ) : (
          <ol className="space-y-1">
            {loan.source_records.map((source) => (
              <li key={source.id} className="rounded border border-slate-200">
                <button
                  type="button"
                  onClick={() => setExpandedSource(expandedSource === source.id ? null : source.id)}
                  className="flex w-full items-center gap-3 px-3 py-2 text-left text-sm hover:bg-slate-50"
                >
                  <span className="font-mono text-xs text-slate-800">{source.source_file}</span>
                  <span className="text-xs text-slate-500">row {source.source_row_number ?? "—"}</span>
                  <Badge tone="neutral">{source.source_system ?? "—"}</Badge>
                  {source.import_status !== "success" && <Badge tone="critical">{source.import_status}</Badge>}
                  <span className="ml-auto text-xs text-slate-400">
                    {expandedSource === source.id ? "hide" : "raw data"}
                  </span>
                </button>
                {expandedSource === source.id && (
                  <div className="border-t border-slate-200 p-3">
                    <p className="mb-1 text-xs text-slate-500">Uploaded input data, retained verbatim as evidence.</p>
                    <Json value={source.raw_data} />
                  </div>
                )}
              </li>
            ))}
          </ol>
        )}
      </Card>
    </div>
  );
}
