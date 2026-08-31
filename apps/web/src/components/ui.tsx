"use client";

import type { ReactNode } from "react";
import type { ExceptionStatus, ReviewerStatus, Severity } from "@/lib/types";

export function Card({ title, actions, children }: { title?: ReactNode; actions?: ReactNode; children: ReactNode }) {
  return (
    <section className="overflow-hidden rounded-xl border border-[#24384b] bg-[#101c29] shadow-[0_12px_40px_rgba(0,0,0,.14)]">
      {(title || actions) && <header className="flex items-center justify-between gap-4 border-b border-[#24384b] bg-[#142536]/70 px-5 py-3.5"><h2 className="text-sm font-semibold tracking-tight text-[#e8eef5]">{title}</h2>{actions}</header>}
      <div className="p-5">{children}</div>
    </section>
  );
}

const SEVERITY_STYLES: Record<Severity, string> = { critical: "bg-[#ef7f83]/15 text-[#ff9b9f] ring-[#ef7f83]/30", high: "bg-[#f1bb68]/15 text-[#ffd18c] ring-[#f1bb68]/30", medium: "bg-[#f1bb68]/10 text-[#f1cf8b] ring-[#f1bb68]/25", low: "bg-[#52d5a0]/12 text-[#78e4b8] ring-[#52d5a0]/25" };
const STATUS_STYLES: Record<string, string> = { open: "bg-[#52c7e8]/12 text-[#79d9f0] ring-[#52c7e8]/25", in_review: "bg-[#52c7e8]/12 text-[#79d9f0] ring-[#52c7e8]/25", resolved: "bg-[#52d5a0]/12 text-[#78e4b8] ring-[#52d5a0]/25", rejected: "bg-[#8b9aab]/12 text-[#b5c2ce] ring-[#8b9aab]/25", pending: "bg-[#52c7e8]/12 text-[#79d9f0] ring-[#52c7e8]/25", accepted: "bg-[#52d5a0]/12 text-[#78e4b8] ring-[#52d5a0]/25", edited: "bg-[#f1bb68]/12 text-[#ffd18c] ring-[#f1bb68]/25" };

export function Badge({ children, tone = "neutral" }: { children: ReactNode; tone?: string }) { const style = SEVERITY_STYLES[tone as Severity] ?? STATUS_STYLES[tone] ?? "bg-[#8b9aab]/12 text-[#b5c2ce] ring-[#8b9aab]/25"; return <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-semibold capitalize ring-1 ring-inset ${style}`}>{children}</span>; }
export function SeverityBadge({ severity }: { severity: Severity }) { return <Badge tone={severity}>{severity}</Badge>; }
export function StatusBadge({ status }: { status: ExceptionStatus | ReviewerStatus | string }) { return <Badge tone={status}>{String(status).replace(/_/g, " ")}</Badge>; }

export function Button({ children, variant = "primary", ...props }: React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "secondary" | "danger" }) {
  const styles = { primary: "bg-[#52c7e8] text-[#07121b] hover:bg-[#79d9f0]", secondary: "border border-[#35516a] bg-[#142536] text-[#e8eef5] hover:border-[#52c7e8] hover:bg-[#193044]", danger: "border border-[#ef7f83]/40 bg-[#ef7f83]/10 text-[#ff9b9f] hover:bg-[#ef7f83]/20" }[variant];
  return <button {...props} className={`inline-flex items-center justify-center rounded-lg px-3.5 py-2 text-sm font-semibold transition disabled:cursor-not-allowed disabled:opacity-50 ${styles} ${props.className ?? ""}`}>{children}</button>;
}
export function ErrorNote({ error }: { error: unknown }) { if (!error) return null; const message = error instanceof Error ? error.message : String(error); return <div role="alert" className="rounded-lg border border-[#ef7f83]/30 bg-[#ef7f83]/10 px-3 py-2 text-sm text-[#ffb1b4]">{message}</div>; }
export function Empty({ children }: { children: ReactNode }) { return <p className="py-10 text-center text-sm text-[#8b9aab]">{children}</p>; }
export function Loading({ label = "Loading…" }: { label?: string }) { return <div className="flex items-center gap-3 py-10 text-sm text-[#8b9aab]"><span className="size-3 animate-spin rounded-full border-2 border-[#35516a] border-t-[#52c7e8]" />{label}</div>; }
export function Forbidden({ action }: { action?: string }) { return <div className="rounded-lg border border-[#f1bb68]/30 bg-[#f1bb68]/10 px-4 py-3 text-sm text-[#ffd18c]">Your role cannot {action ?? "perform this action"}.</div>; }
export function Table({ head, children }: { head: ReactNode[]; children: ReactNode }) { return <div className="overflow-x-auto"><table className="w-full border-collapse text-sm"><thead><tr className="border-b border-[#24384b] text-left text-[10px] uppercase tracking-[0.14em] text-[#8b9aab]">{head.map((cell, index) => <th key={index} className="px-3 py-3 font-semibold">{cell}</th>)}</tr></thead><tbody>{children}</tbody></table></div>; }
export function KeyValue({ rows }: { rows: [string, ReactNode][] }) { return <dl className="grid grid-cols-[minmax(9rem,auto)_1fr] gap-x-4 gap-y-2 text-sm">{rows.map(([key, value]) => <div key={key} className="contents"><dt className="text-[#8b9aab]">{key}</dt><dd className="text-[#e8eef5]">{value ?? <span className="text-[#607286]">—</span>}</dd></div>)}</dl>; }
export function Money({ value }: { value: number | null | undefined }) { if (value === null || value === undefined) return <span className="text-[#607286]">—</span>; return <span className="tabular-nums">{value.toLocaleString(undefined, { style: "currency", currency: "USD" })}</span>; }
export function Json({ value }: { value: unknown }) { if (value === null || value === undefined) return <span className="text-[#607286]">—</span>; return <pre className="max-h-64 overflow-auto rounded-lg border border-[#24384b] bg-[#09111b] p-3 text-xs text-[#b5c2ce]">{JSON.stringify(value, null, 2)}</pre>; }
