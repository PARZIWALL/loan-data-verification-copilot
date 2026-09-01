# Demo Video Script

**Target: 4:50 (hard cap 5:00).** 681 words of narration — about 4:32 spoken at a natural
150 wpm, leaving ~18s of deliberate silence where the video needs it (upload processing, the
hash on screen).

Built for record-audio-first, then screen-capture to match. The **audio column is the master
timeline** — record it in the eight numbered segments so you can stitch and nudge each one
independently rather than re-recording a single long take.

---

## Pre-flight (do this before you hit record)

**1. Reset the demo data.** This matters: the hero loan L-1001 gets consumed by the demo, so
recording twice against the same database means the second take has nothing to show.

```bash
# stop the API if running, then:
cd apps/api
rm -f demo_live.db
DATABASE_URL="sqlite:///./demo_live.db" python -m uvicorn app.main:app --port 8000
# in another shell:
python scripts/seed_demo.py --url http://127.0.0.1:8000
```

Expected after seeding: **40 loans · 18 open exceptions · 12 rule types · quality 0.625**,
Verified Records empty. If those numbers don't match, reseed before recording.

**2. Browser setup.** Hide the bookmarks bar. Zoom to ~110% so table text is readable when
compressed. Use two windows (or one window + one incognito) so you can switch roles instantly
instead of logging out on camera — role switching burns 8 seconds you don't have.

**3. Know the AI risk.** The copilot defers to `request_human_review` on roughly **one run in
three** — documented and intentional. If it defers while recording, that's not a failure, it's
the safety property. Either click Generate again (legitimate, one click) and cut the retake, or
use the fallback line in Segment 4. Don't fake it.

**4. Pre-position tabs**: `docs/AI_DEVELOPMENT_LOG.md` and a terminal ready to run
`pytest -q`, for Segment 7.

---

## Segment 1 — Cold open · 0:00–0:22 (56 words · ~22s narration)

> **AUDIO**
> Loan data almost never arrives clean. It comes from servicers, origination systems, and
> spreadsheets that disagree with each other.
>
> This is a Loan Data Verification Copilot. It turns a messy loan tape into verified, traceable
> records — with an AI assistant that can recommend, but can never act on its own.
>
> That distinction is the whole design.

**VIDEO** — Login screen, still. Let it breathe. Slow scroll over the three role cards at
"recommend, but can never act."

---

## Segment 2 — Data Operator · 0:22–1:00 (84 words · ~34s narration)

> **AUDIO**
> We start as a Data Operator. Only this role can bring data in.
>
> I'm uploading a loan tape of forty records. Every raw row is stored exactly as it arrived,
> with its file, row number, and timestamp — so nothing is ever silently overwritten.
>
> One row fails immediately. A principal value of "not-a-number" can't be normalized, so it's
> rejected and reported rather than quietly dropped.
>
> Now a servicer update for the same loans. Validation runs automatically on ingest — I don't
> click anything to trigger it.

**VIDEO** — Log in as `data_operator` → Upload → `data/loan_tape.csv`. Pause on the import
summary: **40 imported / 1 failed**. Hover the failed row so the reason is legible. Then upload
`data/servicer_update.csv`.

---

## Segment 3 — What validation found · 1:00–1:25 (52 words · ~21s narration)

> **AUDIO**
> Seventeen deterministic rules just ran across every loan. Eighteen exceptions, twelve
> different failure types — balances exceeding principal, invalid state codes, stale records,
> duplicate borrowers.
>
> Data quality sits at sixty-two point five percent. Nothing here is AI-generated. These are
> plain, auditable rules, and they're the authority the AI is not allowed to overrule.

**VIDEO** — Dashboard: linger on the quality score and severity breakdown. Switch to the
Reviewer window → Exception Queue. Scroll the list once so the variety of rule types registers.

---

## Segment 4 — Reviewer + AI copilot · 1:25–2:50 (219 words · ~88s narration) ⭐ THE CORE

> **AUDIO**
> Now the Reviewer. Here's the interesting one: a source conflict on loan L-1001.
>
> The evidence explains itself. The loan tape says the current balance is ninety-five thousand.
> The servicer update — row two, a later file — says eighty-two thousand. The system doesn't
> guess which is right. It surfaces the disagreement and stops.
>
> This is where the copilot comes in. It only ever sees one thing: a read-only evidence packet
> built for this single exception. No database access, no other loans.
>
> It recommends correcting the balance to eighty-two thousand, at ninety-five percent
> confidence, and it cites the exact source row that supports it. That citation is checked
> against the packet — if the model invented a file or row that doesn't exist, the whole
> recommendation is rejected before it's ever stored.
>
> It also can't invent values. The number it proposes has to already appear in the evidence.
> A plausible guess is not good enough.
>
> I accept it. The field updates, revalidation runs, and the exception resolves itself.
>
> And look at the history: two actions, both tagged AI-assisted, both linked back to the
> recommendation that caused them. You can always tell what the AI suggested and what a human
> actually did.

**VIDEO** — Open exception on L-1001 → scroll to **source comparison** (hold 3s on the
highlighted 95000 vs 82000 row) → click **Generate AI recommendation** → hold on the
recommendation card: type badge, confidence bar, the cited `servicer_update.csv row 2` → click
**Accept** → show status flip to **resolved** → scroll to Review history, hold on the two
**AI-assisted** badges.

> **Fallback if it defers:** *"This run, the copilot declined to propose a value — it judged the
> evidence insufficient. That's the intended behaviour, and it happens about a third of the
> time. I'll ask again."* Then click Generate again.

---

## Segment 5 — Verification and hashing · 2:50–3:25 (72 words · ~29s narration)

> **AUDIO**
> With no unresolved exceptions left, this loan can be verified.
>
> Verification is a separate, deliberate step — resolving an exception doesn't silently promote
> anything. It writes an immutable snapshot: the data at this moment, its source lineage, and
> the validation summary.
>
> That snapshot is fingerprinted with SHA-256. The hash covers exactly those three things, so
> if the live loan changes tomorrow, this record and its hash don't move. That's what makes it
> evidence.

**VIDEO** — Click **Verify this loan** → hold on the success panel with the full hash visible.
Let the hash sit on screen for a beat; it's the money shot for traceability.

---

## Segment 6 — Data Consumer · 3:25–4:05 (96 words · ~38s narration)

> **AUDIO**
> Third role: the Data Consumer. They consume verified data — and that's all they can do. No
> uploading, no editing, no approving. The API enforces that, not just the interface.
>
> Here's the record we just created, with its hash. The quality score moved too, because one
> more loan is now clean.
>
> They can export it as JSON — and the export serves the stored snapshot, never a re-read of
> the live loan, so it can't drift.
>
> And every step is in the audit trail: the upload, the validation, the AI recommendation, the
> human decision, the verification, the export.

**VIDEO** — Switch to Data Consumer window → Verified Records (L-1001 now listed) → open it →
copy hash → **Export JSON** (show the download) → Audit Trail → expand one or two events,
ideally `ai_recommendation_dispositioned`.

---

## Segment 7 — Architecture and honest limits · 4:05–4:40 (83 words · ~33s narration)

> **AUDIO**
> Under it all: FastAPI, SQLAlchemy, a Next.js console, and two hundred and ninety tests.
>
> The core rule is that AI output flows into a recommendation table, and only a human decision
> writes to loan data. The AI physically cannot mutate a record.
>
> Honestly, the limits: the copilot only proposes a correction when the evidence contains the
> answer, so most exception types get routed to human review by design. Postgres is supported
> but only SQLite was actually exercised. And authentication here is development-grade.

**VIDEO** — Quick cut: `pytest -q` result on screen (290 passed) → scroll
`docs/AI_DEVELOPMENT_LOG.md` briefly → land on the README's **Known limitations** section as you
say the last sentence.

---

## Segment 8 — Close · 4:40–4:50 (19 words · ~8s narration)

> **AUDIO**
> Messy data in, verified and traceable data out — with an AI that assists the reviewer and
> never replaces them.

**VIDEO** — Return to the Verified Records screen showing L-1001 and its hash. Hold. Fade.

---

## Timing summary

| # | Segment | Duration | Running |
|---|---|---|---|
| 1 | Cold open | 0:22 | 0:22 |
| 2 | Data Operator · ingest | 0:38 | 1:00 |
| 3 | Validation results | 0:25 | 1:25 |
| 4 | **Reviewer + AI copilot** | **1:25** | 2:50 |
| 5 | Verification + hash | 0:35 | 3:25 |
| 6 | Data Consumer | 0:40 | 4:05 |
| 7 | Architecture + limits | 0:35 | 4:40 |
| 8 | Close | 0:10 | **4:50** |

Segment 4 gets the most time on purpose — AI Feature Quality and Traceability are 25 of the
100 judging points, and both land there.

## If you need to cut to fit

Cut in this order, and stop as soon as you're under: Segment 3's dashboard lingering →
Segment 6's audit-trail expansion → Segment 7's test-run cut. **Never** cut the citation beat
or the AI-assisted badges in Segment 4, or the hash in Segment 5 — those are the two things
that separate this from a CRUD app with a chatbot bolted on.

## Delivery notes

- Say the numbers slowly: *"ninety-five thousand"*, *"eighty-two thousand"*, *"SHA-256"*.
- Pause a half-beat before *"and it cites the exact source row"* — it's the most important
  claim in the video.
- Don't rush the honest-limitations lines. The brief explicitly rewards them, and reading them
  confidently sounds like engineering judgment rather than an apology.
