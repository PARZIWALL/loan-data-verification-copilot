"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import { useApiErrorHandler } from "@/lib/auth";
import type { LoanAuditTrail } from "@/lib/types";
import { Badge, Button, Card, Empty, ErrorNote, Json } from "@/components/ui";

export default function AuditPage() {
  const handleError = useApiErrorHandler();
  const [loanId, setLoanId] = useState("");
  const [trail, setTrail] = useState<LoanAuditTrail | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const [expanded, setExpanded] = useState<number | null>(null);

  async function load(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      setTrail(await api.auditTrail(loanId.trim(), { page_size: 200 }));
    } catch (loadError) {
      setTrail(null);
      setError(loadError);
      handleError(loadError);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-semibold text-slate-900">Audit Trail</h1>
        <p className="text-sm text-slate-600">
          Every event recorded against a loan, oldest first. The log is append-only.
        </p>
      </div>

      <Card>
        <form onSubmit={load} className="flex items-end gap-3">
          <div className="min-w-56 flex-1">
            <label htmlFor="loan" className="block text-xs font-medium text-slate-600">Loan ID</label>
            <input
              id="loan"
              value={loanId}
              onChange={(event) => setLoanId(event.target.value)}
              placeholder="L-1001"
              className="mt-1 w-full rounded border border-slate-300 px-3 py-1.5 font-mono text-sm"
            />
          </div>
          <Button type="submit" disabled={!loanId.trim() || busy}>{busy ? "Loading…" : "View trail"}</Button>
        </form>
      </Card>

      <ErrorNote error={error} />

      {trail && (
        <Card title={`${trail.total} events for ${trail.loan_id}`}>
          {trail.items.length === 0 ? (
            <Empty>No audit events for this loan.</Empty>
          ) : (
            <ol className="space-y-1">
              {trail.items.map((event) => (
                <li key={event.id} className="rounded border border-slate-200">
                  <button
                    type="button"
                    onClick={() => setExpanded(expanded === event.id ? null : event.id)}
                    className="flex w-full items-center gap-3 px-3 py-2 text-left text-sm hover:bg-slate-50"
                  >
                    <span className="w-44 shrink-0 text-xs text-slate-400">{event.created_at}</span>
                    <Badge tone="neutral">{event.actor ?? "system"}</Badge>
                    <span className="font-mono text-xs text-slate-800">{event.event_type}</span>
                    <span className="ml-auto text-xs text-slate-400">{expanded === event.id ? "hide" : "details"}</span>
                  </button>
                  {expanded === event.id && (
                    <div className="border-t border-slate-200 p-3"><Json value={event.details} /></div>
                  )}
                </li>
              ))}
            </ol>
          )}
        </Card>
      )}
    </div>
  );
}
