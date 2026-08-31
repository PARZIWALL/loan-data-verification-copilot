"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import { useApiErrorHandler } from "@/lib/auth";
import type { LoanListItem, Paginated } from "@/lib/types";
import { Badge, Button, Card, Empty, ErrorNote, Loading, Money, Table } from "@/components/ui";

export default function LoansPage() {
  const handleError = useApiErrorHandler();
  const [data, setData] = useState<Paginated<LoanListItem> | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [search, setSearch] = useState("");
  const [onlyIssues, setOnlyIssues] = useState(false);
  const [page, setPage] = useState(1);

  const load = useCallback(() => {
    api
      .listLoans({ search: search || undefined, has_open_exceptions: onlyIssues || undefined, page, page_size: 25 })
      .then((result) => { setData(result); setError(null); })
      .catch((loadError) => { setError(loadError); handleError(loadError); });
  }, [search, onlyIssues, page, handleError]);

  useEffect(() => { load(); }, [load]);

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-semibold text-slate-900">Loans</h1>
        <p className="text-sm text-slate-600">Canonical portfolio with current review state.</p>
      </div>

      <Card>
        <div className="flex flex-wrap items-end gap-3">
          <div className="min-w-56 flex-1">
            <label htmlFor="search" className="block text-xs font-medium text-slate-600">Search</label>
            <input
              id="search"
              value={search}
              placeholder="Loan ID or borrower ID"
              onChange={(event) => { setSearch(event.target.value); setPage(1); }}
              className="mt-1 w-full rounded border border-slate-300 px-3 py-1.5 text-sm"
            />
          </div>
          <label className="flex items-center gap-2 pb-1.5 text-sm text-slate-700">
            <input
              type="checkbox"
              checked={onlyIssues}
              onChange={(event) => { setOnlyIssues(event.target.checked); setPage(1); }}
            />
            Only loans with open exceptions
          </label>
        </div>
      </Card>

      <ErrorNote error={error} />

      <Card>
        {!data ? (
          <Loading label="Loading loans…" />
        ) : data.items.length === 0 ? (
          <Empty>No loans match these filters.</Empty>
        ) : (
          <>
            <Table head={["Loan", "Borrower", "State", "Principal", "Balance", "Status", "Open issues", "Verified", ""]}>
              {data.items.map((loan) => (
                <tr key={loan.loan_id} className="border-b border-slate-100 hover:bg-slate-50">
                  <td className="px-3 py-2 font-mono text-xs">{loan.loan_id}</td>
                  <td className="px-3 py-2 font-mono text-xs text-slate-500">{loan.borrower_id ?? "—"}</td>
                  <td className="px-3 py-2">{loan.borrower_state ?? "—"}</td>
                  <td className="px-3 py-2"><Money value={loan.original_principal} /></td>
                  <td className="px-3 py-2"><Money value={loan.current_balance} /></td>
                  <td className="px-3 py-2 text-xs">{loan.payment_status ?? "—"}</td>
                  <td className="px-3 py-2">
                    {loan.open_exception_count > 0
                      ? <Badge tone="open">{loan.open_exception_count}</Badge>
                      : <span className="text-xs text-slate-400">none</span>}
                  </td>
                  <td className="px-3 py-2">
                    {loan.verified ? <Badge tone="resolved">verified</Badge> : <span className="text-xs text-slate-400">—</span>}
                  </td>
                  <td className="px-3 py-2 text-right">
                    <Link href={`/loans/${loan.loan_id}`} className="text-sm font-medium text-slate-900 underline">Open</Link>
                  </td>
                </tr>
              ))}
            </Table>

            {data.total_pages > 1 && (
              <div className="mt-3 flex items-center justify-between text-sm">
                <span className="text-slate-500">Page {data.page} of {data.total_pages} · {data.total} loans</span>
                <div className="flex gap-2">
                  <Button variant="secondary" disabled={page <= 1} onClick={() => setPage((current) => current - 1)}>Previous</Button>
                  <Button variant="secondary" disabled={page >= data.total_pages} onClick={() => setPage((current) => current + 1)}>Next</Button>
                </div>
              </div>
            )}
          </>
        )}
      </Card>
    </div>
  );
}
