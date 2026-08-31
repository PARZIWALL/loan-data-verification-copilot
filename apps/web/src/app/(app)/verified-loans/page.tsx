"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import { useApiErrorHandler } from "@/lib/auth";
import type { Paginated, VerifiedLoan } from "@/lib/types";
import { Badge, Button, Card, Empty, ErrorNote, Loading, Table } from "@/components/ui";

export default function VerifiedLoansPage() {
  const handleError = useApiErrorHandler();
  const [data, setData] = useState<Paginated<VerifiedLoan> | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [page, setPage] = useState(1);

  const load = useCallback(() => {
    api
      .listVerified({ page, page_size: 25 })
      .then((result) => { setData(result); setError(null); })
      .catch((loadError) => { setError(loadError); handleError(loadError); });
  }, [page, handleError]);

  useEffect(() => { load(); }, [load]);

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-semibold text-slate-900">Verified Records</h1>
        <p className="text-sm text-slate-600">
          Immutable snapshots taken at verification time, each fingerprinted with SHA-256.
        </p>
      </div>

      <ErrorNote error={error} />

      <Card>
        {!data ? (
          <Loading label="Loading verified records…" />
        ) : data.items.length === 0 ? (
          <Empty>No verified records yet. A reviewer creates one once a loan has no unresolved exceptions.</Empty>
        ) : (
          <>
            <Table head={["Loan", "Verified by", "Verified at", "Record hash", "Exported", ""]}>
              {data.items.map((record) => (
                <tr key={record.verified_loan_id} className="border-b border-slate-100 hover:bg-slate-50">
                  <td className="px-3 py-2 font-mono text-xs">{record.loan_id}</td>
                  <td className="px-3 py-2 text-sm">{record.verified_by ?? "—"}</td>
                  <td className="px-3 py-2 text-xs text-slate-500">{record.verification_timestamp ?? "—"}</td>
                  <td className="px-3 py-2 font-mono text-xs text-slate-600">
                    {record.record_hash ? `${record.record_hash.slice(0, 16)}…` : "—"}
                  </td>
                  <td className="px-3 py-2">
                    {record.exported ? <Badge tone="resolved">exported</Badge> : <span className="text-xs text-slate-400">no</span>}
                  </td>
                  <td className="px-3 py-2 text-right">
                    <Link href={`/verified-loans/${record.verified_loan_id}`} className="text-sm font-medium text-slate-900 underline">
                      Open
                    </Link>
                  </td>
                </tr>
              ))}
            </Table>

            {data.total_pages > 1 && (
              <div className="mt-3 flex items-center justify-between text-sm">
                <span className="text-slate-500">Page {data.page} of {data.total_pages} · {data.total} records</span>
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
