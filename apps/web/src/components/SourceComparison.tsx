"use client";

/**
 * Canonical value vs. every source that carries the same field.
 *
 * This is the view that makes a source_conflict self-explanatory: one row per field,
 * one column per source record, disagreements highlighted. Source content is uploaded
 * customer data and is labelled as untrusted input, never as instruction.
 */

import type { CanonicalLoan, LoanSourceRecord } from "@/lib/types";
import { Card } from "@/components/ui";

function normalize(value: unknown): string | null {
  if (value === null || value === undefined || value === "") return null;
  const asNumber = Number(value);
  if (!Number.isNaN(asNumber) && String(value).trim() !== "") return String(asNumber);
  return String(value).trim();
}

export function SourceComparison({
  canonicalLoan,
  sourceEvidence,
  focusFields,
}: {
  canonicalLoan: CanonicalLoan;
  sourceEvidence: LoanSourceRecord[];
  focusFields: string[];
}) {
  // Only show fields that at least one source actually carries, so the table stays
  // about the disagreement rather than listing the whole loan.
  const fields = focusFields.filter((field) =>
    sourceEvidence.some((source) => source.raw_data && field in source.raw_data),
  );

  if (fields.length === 0 || sourceEvidence.length === 0) {
    return (
      <Card title="Source comparison">
        <p className="text-sm text-slate-500">
          No source records carry the fields involved in this exception.
        </p>
      </Card>
    );
  }

  return (
    <Card title="Source comparison">
      <p className="mb-3 text-xs text-slate-500">
        Source content is uploaded input data, shown as evidence only. Cells that disagree with the
        canonical value are highlighted.
      </p>
      <div className="overflow-x-auto">
        <table className="w-full border-collapse text-sm">
          <thead>
            <tr className="border-b border-slate-200 text-left text-xs text-slate-500">
              <th className="px-3 py-2 font-medium">Field</th>
              <th className="px-3 py-2 font-medium">Canonical</th>
              {sourceEvidence.map((source) => (
                <th key={source.id} className="px-3 py-2 font-medium">
                  <span className="block font-mono text-xs text-slate-700">{source.source_file}</span>
                  <span className="block text-[11px] font-normal text-slate-400">
                    row {source.source_row_number ?? "—"} · {source.imported_at ?? ""}
                  </span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {fields.map((field) => {
              const canonicalValue = (canonicalLoan as unknown as Record<string, unknown>)[field];
              const canonicalNorm = normalize(canonicalValue);
              return (
                <tr key={field} className="border-b border-slate-100">
                  <td className="px-3 py-2 font-mono text-xs text-slate-700">{field}</td>
                  <td className="px-3 py-2 tabular-nums font-medium">{String(canonicalValue ?? "—")}</td>
                  {sourceEvidence.map((source) => {
                    const raw = source.raw_data?.[field];
                    const present = source.raw_data ? field in source.raw_data : false;
                    const differs = present && normalize(raw) !== canonicalNorm;
                    return (
                      <td
                        key={source.id}
                        className={`px-3 py-2 tabular-nums ${
                          differs ? "bg-amber-50 font-medium text-amber-900" : "text-slate-600"
                        }`}
                      >
                        {present ? String(raw ?? "—") : <span className="text-slate-300">—</span>}
                        {differs && <span className="ml-1 text-xs">⚠</span>}
                      </td>
                    );
                  })}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </Card>
  );
}
