"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import { useApiErrorHandler, useAuth } from "@/lib/auth";
import type { Summary } from "@/lib/types";
import { Card, ErrorNote, Loading, SeverityBadge } from "@/components/ui";

function Stat({ label, value, hint, emphasis }: { label: string; value: string | number; hint?: string; emphasis?: boolean }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4">
      <p className="text-xs uppercase tracking-wide text-slate-500">{label}</p>
      <p className={`mt-1 tabular-nums ${emphasis ? "text-3xl font-semibold" : "text-2xl font-medium"} text-slate-900`}>
        {value}
      </p>
      {hint && <p className="mt-0.5 text-xs text-slate-500">{hint}</p>}
    </div>
  );
}

export default function DashboardPage() {
  const { user } = useAuth();
  const handleError = useApiErrorHandler();
  const [summary, setSummary] = useState<Summary | null>(null);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    api.summary().then(setSummary).catch((loadError) => {
      setError(loadError);
      handleError(loadError);
    });
  }, [handleError]);

  if (error) return <ErrorNote error={error} />;
  if (!summary) return <Loading label="Loading portfolio summary…" />;

  const role = user!.role;
  const quality = Math.round(summary.data_quality_score * 100);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-slate-900">Dashboard</h1>
        <p className="text-sm text-slate-600">Portfolio-wide verification state.</p>
      </div>

      {role === "data_operator" && (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <Stat label="Source files" value={summary.ingestion.files} />
          <Stat label="Rows imported" value={summary.ingestion.rows_imported} />
          <Stat label="Rows failed" value={summary.ingestion.rows_failed} hint="Could not be normalized" />
          <Stat label="Corrections needed" value={summary.loans.with_open_exceptions} hint="Loans with open exceptions" />
        </div>
      )}

      {role === "reviewer" && (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <Stat label="Open exceptions" value={summary.exceptions.open} emphasis />
          <Stat label="In review" value={summary.exceptions.in_review} />
          <Stat label="Resolved" value={summary.exceptions.resolved} />
          <Stat label="AI pending review" value={summary.ai.pending} hint={`${summary.ai.recommendations} generated`} />
        </div>
      )}

      {role === "data_consumer" && (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <Stat label="Data quality score" value={`${quality}%`} emphasis hint="Loans with no unresolved exception" />
          <Stat label="Verified records" value={summary.verification.verified_records} />
          <Stat label="Exported" value={summary.verification.exported} />
          <Stat label="Audit events" value={summary.audit.events} />
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Portfolio">
          <div className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
            <div><p className="text-slate-500">Loans</p><p className="text-lg tabular-nums">{summary.loans.total}</p></div>
            <div><p className="text-slate-500">Clean</p><p className="text-lg tabular-nums">{summary.loans.clean}</p></div>
            <div><p className="text-slate-500">With issues</p><p className="text-lg tabular-nums">{summary.loans.with_open_exceptions}</p></div>
            <div><p className="text-slate-500">Verified</p><p className="text-lg tabular-nums">{summary.loans.verified}</p></div>
          </div>
          <div className="mt-4">
            <div className="flex items-center justify-between text-xs text-slate-500">
              <span>Data quality</span><span className="tabular-nums">{quality}%</span>
            </div>
            <div className="mt-1 h-2 overflow-hidden rounded bg-slate-100">
              <div className="h-full bg-slate-900" style={{ width: `${quality}%` }} />
            </div>
          </div>
        </Card>

        <Card title="Validation">
          <div className="grid grid-cols-3 gap-3 text-sm">
            <div><p className="text-slate-500">Checks run</p><p className="text-lg tabular-nums">{summary.validation.total_results}</p></div>
            <div><p className="text-slate-500">Passed</p><p className="text-lg tabular-nums text-emerald-700">{summary.validation.passed}</p></div>
            <div><p className="text-slate-500">Failed</p><p className="text-lg tabular-nums text-red-700">{summary.validation.failed}</p></div>
          </div>
          <p className="mt-3 text-xs text-slate-500">Last run: {summary.validation.latest_run_at ?? "never"}</p>
        </Card>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Exceptions by severity">
          <div className="space-y-2">
            {(["critical", "high", "medium", "low"] as const).map((severity) => (
              <div key={severity} className="flex items-center justify-between">
                <SeverityBadge severity={severity} />
                <span className="tabular-nums text-sm">{summary.exceptions.by_severity[severity] ?? 0}</span>
              </div>
            ))}
          </div>
        </Card>

        <Card
          title="Top exception types"
          actions={
            role === "reviewer" ? (
              <Link href="/exceptions" className="text-xs font-medium text-slate-600 hover:text-slate-900">
                Open queue →
              </Link>
            ) : null
          }
        >
          {summary.exceptions.by_type.length === 0 ? (
            <p className="text-sm text-slate-500">No exceptions.</p>
          ) : (
            <ul className="space-y-1.5">
              {summary.exceptions.by_type.slice(0, 8).map((item) => (
                <li key={item.type} className="flex items-center justify-between text-sm">
                  <span className="font-mono text-xs text-slate-700">{item.type}</span>
                  <span className="tabular-nums text-slate-900">{item.count}</span>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
    </div>
  );
}
