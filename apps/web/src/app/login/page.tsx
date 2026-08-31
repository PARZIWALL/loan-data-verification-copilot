"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth";
import { Button, ErrorNote } from "@/components/ui";

// Seeded by the backend on startup (apps/api/app/core/seed.py). Shown on the login
// screen because the brief requires test credentials for all three roles, and the
// demo involves switching between them repeatedly.
const TEST_ACCOUNTS = [
  { username: "data_operator", password: "data_operator_dev", label: "Data Operator", can: "Upload loan tapes" },
  { username: "reviewer", password: "reviewer_dev", label: "Reviewer", can: "Work the exception queue, use the AI copilot, verify" },
  { username: "data_consumer", password: "data_consumer_dev", label: "Data Consumer", can: "Read verified records, audit trail, export" },
];

export default function LoginPage() {
  const { login } = useAuth();
  const router = useRouter();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: React.FormEvent, presetUser?: string, presetPass?: string) {
    event.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await login(presetUser ?? username, presetPass ?? password);
      router.push("/dashboard");
    } catch (loginError) {
      setError(loginError);
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="mx-auto flex min-h-screen max-w-5xl items-center justify-center px-6 py-12">
      <div className="grid w-full gap-8 md:grid-cols-2">
        <div className="space-y-4">
          <div>
            <h1 className="text-2xl font-semibold text-slate-900">Loan Data Verification Copilot</h1>
            <p className="mt-1 text-sm text-slate-600">
              Ingest messy loan records, validate them deterministically, review exceptions with an
              evidence-grounded AI copilot, and produce tamper-evident verified records.
            </p>
          </div>

          <form onSubmit={submit} className="space-y-3 rounded-lg border border-slate-200 bg-white p-4">
            <div>
              <label htmlFor="username" className="block text-xs font-medium text-slate-600">Username</label>
              <input
                id="username"
                value={username}
                onChange={(event) => setUsername(event.target.value)}
                autoComplete="username"
                className="mt-1 w-full rounded border border-slate-300 px-3 py-1.5 text-sm"
              />
            </div>
            <div>
              <label htmlFor="password" className="block text-xs font-medium text-slate-600">Password</label>
              <input
                id="password"
                type="password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                autoComplete="current-password"
                className="mt-1 w-full rounded border border-slate-300 px-3 py-1.5 text-sm"
              />
            </div>
            <ErrorNote error={error} />
            <Button type="submit" disabled={busy || !username || !password}>
              {busy ? "Signing in…" : "Sign in"}
            </Button>
          </form>
        </div>

        <div className="rounded-lg border border-slate-200 bg-white p-4">
          <h2 className="text-sm font-semibold text-slate-800">Test accounts</h2>
          <p className="mt-1 text-xs text-slate-500">Each role sees a different console.</p>
          <ul className="mt-3 space-y-2">
            {TEST_ACCOUNTS.map((account) => (
              <li key={account.username} className="rounded border border-slate-200 p-3">
                <div className="flex items-center justify-between gap-3">
                  <div>
                    <p className="text-sm font-medium text-slate-900">{account.label}</p>
                    <p className="font-mono text-xs text-slate-500">
                      {account.username} / {account.password}
                    </p>
                  </div>
                  <Button
                    variant="secondary"
                    disabled={busy}
                    onClick={(event) => submit(event, account.username, account.password)}
                  >
                    Use
                  </Button>
                </div>
                <p className="mt-1.5 text-xs text-slate-600">{account.can}</p>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </main>
  );
}
