"use client";

import { useState } from "react";
import Link from "next/link";
import { ApiError, api } from "@/lib/api";
import { useApiErrorHandler, useAuth } from "@/lib/auth";
import type { SourceType, UploadResult } from "@/lib/types";
import { Button, Card, ErrorNote, Forbidden, Table } from "@/components/ui";

const SOURCE_TYPES: { value: SourceType; label: string; hint: string }[] = [
  { value: "loan_tape", label: "Loan tape", hint: "Primary system of record. Creates and updates canonical loans." },
  { value: "servicer_update", label: "Servicer update", hint: "Secondary evidence. Compared against canonical values." },
  { value: "document_manifest", label: "Document manifest", hint: "Supporting evidence of document availability." },
];

export default function UploadPage() {
  const { user } = useAuth();
  const handleError = useApiErrorHandler();
  const [sourceType, setSourceType] = useState<SourceType>("loan_tape");
  const [file, setFile] = useState<File | null>(null);
  const [result, setResult] = useState<UploadResult | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  if (user!.role !== "data_operator") return <Forbidden action="upload files" />;

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!file) return;
    setError(null);
    setResult(null);
    setBusy(true);
    try {
      setResult(await api.upload(file, sourceType));
    } catch (uploadError) {
      setError(uploadError);
      handleError(uploadError);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-slate-900">Upload</h1>
        <p className="text-sm text-slate-600">
          Rows are stored with full source lineage, normalized into canonical loans, and validated
          automatically. Any rule failure becomes an exception for review.
        </p>
      </div>

      <Card title="New import">
        <form onSubmit={submit} className="space-y-4">
          <fieldset className="space-y-2">
            <legend className="text-xs font-medium text-slate-600">Source type</legend>
            {SOURCE_TYPES.map((option) => (
              <label key={option.value} className="flex cursor-pointer items-start gap-2 rounded border border-slate-200 p-2.5">
                <input
                  type="radio"
                  name="source_type"
                  value={option.value}
                  checked={sourceType === option.value}
                  onChange={() => setSourceType(option.value)}
                  className="mt-1"
                />
                <span>
                  <span className="block text-sm font-medium text-slate-900">{option.label}</span>
                  <span className="block text-xs text-slate-500">{option.hint}</span>
                </span>
              </label>
            ))}
          </fieldset>

          <div>
            <label htmlFor="file" className="block text-xs font-medium text-slate-600">CSV file</label>
            <input
              id="file"
              type="file"
              accept=".csv,text/csv"
              onChange={(event) => setFile(event.target.files?.[0] ?? null)}
              className="mt-1 w-full rounded border border-slate-300 px-3 py-1.5 text-sm"
            />
          </div>

          <ErrorNote error={error} />
          {error instanceof ApiError && error.isForbidden && <Forbidden action="upload files" />}

          <Button type="submit" disabled={!file || busy}>
            {busy ? "Importing and validating…" : "Upload"}
          </Button>
        </form>
      </Card>

      {result && (
        <Card title="Import summary">
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
            <div><p className="text-xs text-slate-500">Source</p><p className="font-mono text-sm">{result.source_type}</p></div>
            <div><p className="text-xs text-slate-500">Total rows</p><p className="text-lg tabular-nums">{result.total_rows}</p></div>
            <div><p className="text-xs text-slate-500">Imported</p><p className="text-lg tabular-nums text-emerald-700">{result.imported_rows}</p></div>
            <div><p className="text-xs text-slate-500">Failed</p><p className="text-lg tabular-nums text-red-700">{result.failed_rows}</p></div>
          </div>

          {result.failed_details.length > 0 && (
            <div className="mt-4">
              <h3 className="text-sm font-medium text-slate-800">Rows that could not be imported</h3>
              <p className="mb-2 text-xs text-slate-500">
                These failed normalization, so no canonical loan was created. The raw row is still
                retained with its failure reason.
              </p>
              <Table head={["Row", "Reason"]}>
                {result.failed_details.map((failure) => (
                  <tr key={failure.row_number} className="border-b border-slate-100">
                    <td className="px-3 py-1.5 tabular-nums">{failure.row_number}</td>
                    <td className="px-3 py-1.5 text-red-700">{failure.reason}</td>
                  </tr>
                ))}
              </Table>
            </div>
          )}

          <p className="mt-4 text-sm text-slate-600">
            Validation has already run.{" "}
            <Link href="/loans" className="font-medium text-slate-900 underline">Review the loans →</Link>
          </p>
        </Card>
      )}
    </div>
  );
}
