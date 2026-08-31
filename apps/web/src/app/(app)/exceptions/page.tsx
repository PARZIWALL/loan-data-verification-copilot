"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import { useApiErrorHandler } from "@/lib/auth";
import type { ExceptionQueueItem, Paginated } from "@/lib/types";
import { Button, Card, Empty, ErrorNote, Loading, SeverityBadge, StatusBadge, Table } from "@/components/ui";

const SEVERITIES = ["critical", "high", "medium", "low"];
const STATUSES = ["open", "in_review", "resolved", "rejected"];

export default function ExceptionQueuePage() {
  const handleError = useApiErrorHandler();
  const [data, setData] = useState<Paginated<ExceptionQueueItem> | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);

  const [search, setSearch] = useState("");
  const [severity, setSeverity] = useState("");
  const [status, setStatus] = useState("open");
  const [page, setPage] = useState(1);

  const load = useCallback(() => {
    setLoading(true);
    api
      .listExceptions({ search: search || undefined, severity: severity || undefined, status: status || undefined, page, page_size: 25 })
      .then((result) => {
        setData(result);
        setError(null);
      })
      .catch((loadError) => {
        setError(loadError);
        handleError(loadError);
      })
      .finally(() => setLoading(false));
  }, [search, severity, status, page, handleError]);

  useEffect(() => { load(); }, [load]);

  return (
    <div className="space-y-4">
      <div className="flex items-end justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold text-slate-900">Exception Queue</h1>
          <p className="text-sm text-slate-600">Highest severity first. Open an exception to see its evidence and act on it.</p>
        </div>
        {data && <p className="text-sm tabular-nums text-slate-500">{data.total} matching</p>}
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
          <div>
            <label htmlFor="severity" className="block text-xs font-medium text-slate-600">Severity</label>
            <select
              id="severity"
              value={severity}
              onChange={(event) => { setSeverity(event.target.value); setPage(1); }}
              className="mt-1 rounded border border-slate-300 px-3 py-1.5 text-sm"
            >
              <option value="">All</option>
              {SEVERITIES.map((value) => <option key={value} value={value}>{value}</option>)}
            </select>
          </div>
          <div>
            <label htmlFor="status" className="block text-xs font-medium text-slate-600">Status</label>
            <select
              id="status"
              value={status}
              onChange={(event) => { setStatus(event.target.value); setPage(1); }}
              className="mt-1 rounded border border-slate-300 px-3 py-1.5 text-sm"
            >
              <option value="">All</option>
              {STATUSES.map((value) => <option key={value} value={value}>{value.replace("_", " ")}</option>)}
            </select>
          </div>
        </div>
      </Card>

      <ErrorNote error={error} />

      <Card>
        {loading && !data ? (
          <Loading label="Loading exceptions…" />
        ) : !data || data.items.length === 0 ? (
          <Empty>No exceptions match these filters.</Empty>
        ) : (
          <>
            <Table head={["Severity", "Type", "Loan", "Borrower", "Message", "Status", ""]}>
              {data.items.map((item) => (
                <tr key={item.exception_id} className="border-b border-slate-100 hover:bg-slate-50">
                  <td className="px-3 py-2"><SeverityBadge severity={item.severity} /></td>
                  <td className="px-3 py-2 font-mono text-xs">{item.type}</td>
                  <td className="px-3 py-2 font-mono text-xs">{item.loan_id}</td>
                  <td className="px-3 py-2 font-mono text-xs text-slate-500">{item.borrower_id ?? "—"}</td>
                  <td className="max-w-md truncate px-3 py-2 text-slate-700">{item.message ?? "—"}</td>
                  <td className="px-3 py-2"><StatusBadge status={item.status} /></td>
                  <td className="px-3 py-2 text-right">
                    <Link href={`/exceptions/${item.exception_id}`} className="text-sm font-medium text-slate-900 underline">
                      Review
                    </Link>
                  </td>
                </tr>
              ))}
            </Table>

            {data.total_pages > 1 && (
              <div className="mt-3 flex items-center justify-between text-sm">
                <span className="text-slate-500">Page {data.page} of {data.total_pages}</span>
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
