# Loan Verification Console (frontend template)

Next.js 14 (App Router) + TypeScript + Tailwind. This is a **functional template**: the
data flow, API contracts, role routing and UI states are correct and complete; the visual
design is deliberately plain and is expected to be refined (e.g. with Vercel v0).

> **Not yet built or type-checked.** Node was unavailable on the machine that generated
> this, so `npm install` / `next build` have never been run against it. Expect to fix
> small compile issues on first build.

## Run

```bash
cp .env.local.example .env.local     # point at the API
npm install
npm run dev                          # http://localhost:3000
```

The backend must be running on `NEXT_PUBLIC_API_BASE_URL` (default `http://localhost:8000`)
and its `CORS_ORIGINS` must include this origin — `http://localhost:3000` is allowed by default.

## Test accounts

Seeded by the backend on startup, and listed on the login screen for one-click sign-in:

| Username | Password | Sees |
|---|---|---|
| `data_operator` | `data_operator_dev` | Dashboard, Upload, Loans |
| `reviewer` | `reviewer_dev` | Dashboard, Exception Queue, Loans, Verified Records |
| `data_consumer` | `data_consumer_dev` | Dashboard, Verified Records, Audit Trail |

## Structure

```
src/lib/types.ts    API types mirrored from apps/api/app/schemas — keep in sync
src/lib/api.ts      the only place that talks to the backend
src/lib/auth.tsx    session, role nav, route guard
src/components/     ui.tsx primitives, AIRecommendationPanel, SourceComparison
src/app/(app)/      authenticated screens
```

## Screens

| Route | Role | Purpose |
|---|---|---|
| `/login` | — | Sign in; test accounts listed |
| `/dashboard` | all | Role-specific tiles over `GET /summary` |
| `/upload` | operator | CSV import + import summary with failed rows |
| `/loans`, `/loans/[loanId]` | operator, reviewer | Portfolio and per-loan detail, lineage, re-validate |
| `/exceptions` | reviewer | Filterable exception queue |
| `/exceptions/[exceptionId]` | reviewer | **Centrepiece** — evidence, source comparison, AI panel, decisions, history |
| `/verified-loans`, `/verified-loans/[id]` | consumer, reviewer | Verified snapshots, SHA-256 hash, export |
| `/audit` | consumer | Per-loan audit trail |

## Notes for whoever restyles this

Keep these behaviours — they are graded, not decorative:

1. **The AI panel is advisory and visually separate from the human decision area.** The AI
   can recommend; only a reviewer acts.
2. **Accepting a `request_human_review` recommendation does not resolve the exception.** The
   copy saying so is deliberate.
3. **Review-history rows with an `ai_recommendation_id` are badged "AI-assisted."** That badge
   is the visible proof the AI is a copilot and its suggestions are traceable to real actions.
4. **Source data is labelled as untrusted input.** It comes from uploaded files.
5. **Surface the backend's `detail` message on errors.** It explains *why* an action was
   refused (terminal exception, already dispositioned, non-editable field); a generic
   "Something went wrong" loses that.
6. **`POST /verified-loans` returning `status: "ineligible"` is a 200, not an error.** It must
   render as a normal workflow outcome listing the blocking exceptions.

Component names and props in `components/ui.tsx` are the contract the screens depend on —
restyle their internals freely, but keep the signatures.
