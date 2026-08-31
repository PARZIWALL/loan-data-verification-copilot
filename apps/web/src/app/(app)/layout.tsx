"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect } from "react";
import { ROLE_LABELS, navFor, useAuth } from "@/lib/auth";
import { Button, Loading } from "@/components/ui";

export default function AppLayout({ children }: { children: React.ReactNode }) {
  const { user, loading, logout } = useAuth();
  const router = useRouter();
  const pathname = usePathname();
  useEffect(() => { if (!loading && !user) router.replace("/login"); }, [user, loading, router]);
  if (loading) return <Loading label="Restoring session…" />;
  if (!user) return null;
  const nav = navFor(user.role);
  return <div className="console-grid min-h-screen bg-[#09111b]">
    <div className="mx-auto flex min-h-screen max-w-[1440px] flex-col md:flex-row">
      <aside className="border-b border-[#24384b] bg-[#0d1824]/95 md:flex md:w-64 md:flex-col md:border-b-0 md:border-r">
        <div className="flex items-center justify-between gap-3 px-5 py-5 md:block">
          <Link href="/dashboard" className="flex items-center gap-3"><span className="grid size-9 place-items-center rounded-lg bg-[#52c7e8] text-sm font-black text-[#07121b]">LV</span><span><span className="block text-sm font-bold tracking-tight text-[#e8eef5]">LoanVerify</span><span className="block text-[10px] uppercase tracking-[0.15em] text-[#8b9aab]">Operations</span></span></Link>
          <span className="hidden text-[10px] font-semibold uppercase tracking-[0.18em] text-[#52d5a0] md:mt-10 md:block">Workspace</span>
        </div>
        <nav className="flex gap-1 overflow-x-auto px-3 pb-3 md:flex-col md:px-3 md:py-4" aria-label="Primary navigation">
          {nav.map((item) => { const active = pathname === item.href || pathname.startsWith(`${item.href}/`); return <Link key={item.href} href={item.href} className={`whitespace-nowrap rounded-lg px-3 py-2.5 text-sm font-medium transition ${active ? "bg-[#52c7e8]/12 text-[#79d9f0]" : "text-[#8b9aab] hover:bg-[#142536] hover:text-[#e8eef5]"}`}>{item.label}</Link>; })}
        </nav>
        <div className="mt-auto hidden border-t border-[#24384b] p-4 md:block"><p className="eyebrow">Signed in as</p><p className="mt-1 truncate text-sm font-semibold text-[#e8eef5]">{user.username}</p><p className="text-xs text-[#8b9aab]">{ROLE_LABELS[user.role]}</p><Button variant="secondary" onClick={logout} className="mt-4 w-full">Sign out</Button></div>
      </aside>
      <div className="min-w-0 flex-1"><header className="flex items-center justify-between border-b border-[#24384b] bg-[#0d1824]/70 px-5 py-4 md:px-8"><div><p className="eyebrow">Verification workspace</p><p className="mt-1 text-xs text-[#8b9aab]">Secure, evidence-led loan operations</p></div><div className="flex items-center gap-3 md:hidden"><span className="text-right"><span className="block text-xs font-semibold text-[#e8eef5]">{user.username}</span><span className="block text-[10px] text-[#8b9aab]">{ROLE_LABELS[user.role]}</span></span><Button variant="secondary" onClick={logout}>Exit</Button></div><div className="hidden items-center gap-2 text-xs text-[#52d5a0] md:flex"><span className="size-2 rounded-full bg-[#52d5a0]" />System operational</div></header><main className="mx-auto max-w-7xl px-5 py-6 md:px-8 md:py-8">{children}</main></div>
    </div>
  </div>;
}
