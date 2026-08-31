# AI Development Log

**Intain Campus FinTech Challenge 2026 · Full Stack Track**
**Loan Data Verification Copilot**

How AI and agentic coding tools were used to design, build, test, debug, review and document this
system. It covers the development *process*, not only the AI feature inside the product.

Every claim about the codebase in this document was verified against the repository at the time of
writing: **290 tests passing, 17 validation rules, 24 API routes, 8 commits.**

---

## 1. Context

The product ingests messy loan data, preserves source lineage, normalizes records, runs
deterministic validation, routes failures into a reviewer exception workflow, provides an
evidence-grounded AI copilot, produces immutable verified records with SHA-256 hashes, exports
verified data, and maintains an audit trail.

It was built in small staged increments rather than one large generation pass. After each stage,
focused tests ran first, then regression. Human judgment decided architecture, scope, safety
boundaries, whether a change actually matched the specification, and — repeatedly the most
valuable check — whether a passing test genuinely proved what it claimed.

**Tools used**

| Tool | Role |
|---|---|
| ChatGPT | Architecture planning, task decomposition, prompt design, debugging analysis, review of agent output, project strategy |
| Claude Code | Repository exploration, implementation, testing, debugging, auditing, documentation; executed the staged backend plan |
| GitHub Copilot / Codex | Implementation assistance and continuation of backend work |
| v0 / Vercel AI | Frontend generation and dark-theme redesign, against fixed API contracts |

AI was treated as an implementation partner, not an authority. Generated code was accepted only
after inspection and executable verification.

---

## 2. Method: staged, evidence-driven agentic coding

1. Define the architecture and one narrow milestone.
2. Give the agent a bounded prompt with an explicit definition of done.
3. Require it to inspect existing code before modifying anything.
4. Run focused tests for that milestone.
5. Investigate every failure rather than weakening the assertion.
6. Run the full suite once focused tests are green.
7. Review the implementation against the intended architecture.
8. Freeze the completed area; move on.
9. Periodically run a broad read-only audit before continuing.
10. Only after the backend was stable, move to frontend and submission work.

This mattered more as the system grew. The project reached a state where **many features passed
their own tests while not being connected through the real API lifecycle at all**. A read-only
audit later surfaced startup, authorization, validation-wiring, transaction, schema and
documentation gaps that no unit test had caught. Those were stabilized before AI work continued.

---

## 3. Development stages

### 3.1 Architecture and schema
AI helped define structure, entities, lifecycle, validation boundaries, roles and schema
constraints. A deliberate human decision kept it simple: FastAPI + SQLAlchemy, SQLite locally with
PostgreSQL compatibility maintained where practical — no microservices, queues, or repository
abstraction.

### 3.2 Database and authentication
Agents implemented the SQLAlchemy foundation, migrations, environment-driven configuration, roles,
JWT auth and seeded users.

Two defects surfaced during verification. Application and Alembic config carried hard-coded
PostgreSQL defaults while the environment was SQLite-only; configuration was made
environment-first. Separately, the `back_populates` pairings between AI recommendations, review
actions and exceptions were inconsistent and broke mapper initialization.

### 3.3 Ingestion
CSV intake, normalization, raw-source preservation, lineage, canonical loan create/update,
malformed-row handling, re-upload behaviour and ingestion audit events — tested against
realistically shaped loan data rather than only synthetic ORM objects.

### 3.4 Validation engine
Built deliberately as a deterministic framework: a `validate_loan(loan_id)` entry point, registered
rules, deterministic ordering, complete execution even when an earlier rule fails, structured
PASS/FAIL results, preserved history, atomic persistence and a `validation_executed` audit event.
Seventeen business rules were then added incrementally.

A boundary question arose when a test tried to set a numeric column to the literal string
`"not-a-number"` and failed before validation could run. The conclusion was that malformed raw
values belong to ingestion/normalization while canonical fields stay strongly typed — so the *test*
was corrected rather than the type model weakened.

### 3.5 Exception lifecycle and revalidation
Failed results became exceptions, with no duplicate open exceptions, preserved history, and
revalidation behaviour.

A subtle semantic issue emerged later: because the service only reused *open* exceptions, an
exception a reviewer had explicitly approved could be silently duplicated whenever an unrelated
edit triggered a full revalidation. The fix distinguishes automatic pass-based resolution from a
human business override — a human terminal decision stays authoritative until another human acts.

### 3.6 Reviewer workflow
Exception queue and detail APIs, comments and action history, allowlisted field editing, and
approve / reject / request-correction decisions. AI-driven changes later reused this same mutation
and revalidation path rather than getting a parallel AI-specific one.

### 3.7 Verification, hashing, export
Eligibility checks, immutable snapshot, SHA-256 hash, retrieval, JSON export and an export audit
event. The hash is defined over exactly `final_data`, `source_reference` and
`validation_result_summary` using canonical JSON normalization.

### 3.8 AI evidence and recommendation
Deliberately split so the AI never became an unbounded database agent:

- **7A** deterministic evidence construction
- **7A.1** evidence-quality hardening
- **7B** recommendation engine
- **7C** reviewer disposition

```
exception → EvidencePacket → Groq / openai/gpt-oss-120b → structured recommendation
   → grounding checks → ai_recommendations → human reviewer → existing reviewer workflow
```

The AI is advisory. It cannot mutate loans, exceptions, validation results, review actions or
verified records.

### 3.9 Frontend
The first generated frontend was functional but visually plain. v0 was then given a *targeted
redesign brief* rather than asked to rebuild the app, producing a dark-first fintech operations
console with role-aware navigation, stronger exception-detail UX, evidence comparison, an
explicitly advisory AI panel, and clear separation between AI recommendation and human decision.

A real production build was only possible after a Node PATH problem was resolved. The build then
surfaced security advisories: Next.js was upgraded **14.2.5 → 15.5.24** and postcss pinned via an
override, reaching **0 npm vulnerabilities**. The running frontend was then exercised against the
live backend and real API contracts.

### 3.10 Stabilization and documentation
A read-only master audit found issues invisible to isolated feature tests:

- a fresh clone did not initialize its database (first real request returned *no such table: users*)
- `POST /upload` had no authentication
- validation was never wired into the real API lifecycle
- edit + revalidation spanned two database sessions
- verification was possible without any validation history
- model/migration schema drift
- missing dashboard/summary APIs
- stale README and architecture claims

All were fixed in a dedicated stabilization pass before final frontend and documentation work.

---

## 4. Representative prompts

Genuine excerpts from the development sessions, lightly trimmed.

**1 — Validation engine foundation**
> Implement the validation engine foundation only. Create `validate_loan(loan_id)`, deterministic
> rule registration and ordering, complete execution even when one rule fails, structured PASS/FAIL
> results, atomic persistence, and a `validation_executed` audit event. Do not implement
> business-specific rules, AI, reviewer actions, or verification. Add focused tests and stop.

**2 — Read-only takeover audit**
> You are acting as a senior software architect taking over an existing codebase from another
> coding agent. Fully understand the application, audit what has actually been implemented, verify
> the current state… For every issue classify CRITICAL / HIGH / MEDIUM / LOW. Distinguish confirmed
> defect, likely risk, design concern, missing verification. **Do not exaggerate.**

**3 — Evidence packet hardening (7A.1)**
> Harden the EvidencePacket so it becomes a trustworthy AI context boundary. Provide explicit rule
> metadata for every registered rule, distinguish the original from the latest validation result,
> preserve real source provenance, bound raw source payloads, mark source data as untrusted, derive
> schema/relationship metadata from the actual SQLAlchemy models, and keep construction
> deterministic and read-only. **Do not weaken tests to make implementation pass.**

**4 — AI recommendation safety (7B)**
> Implement a safe evidence-grounded AI recommendation service using Groq and
> `openai/gpt-oss-120b`. The AI is a COPILOT. It is NOT allowed to mutate loans, exceptions,
> validation results, create review actions, approve, reject, verify, export, or directly access
> the database. Enforce structured output, citation grounding, editable-field validation, atomic
> persistence, audit logging, and no-mutation tests. **DO NOT THROW AWAY THE EXISTING
> IMPLEMENTATION — inspect it first and make the smallest necessary corrections.**

**5 — AI disposition (7C)**
> This is where we prove the AI is actually a copilot, not a second hidden decision-maker. Connect
> recommendation → human decision → existing mutation/revalidation paths. Include auditability of
> the disposition: AI recommended X → reviewer accepted/edited/rejected X → actual action recorded.

**6 — Review amendments on an approved plan**
> The stabilization plan is approved with these additions: 0H must use the proven 6A-style test
> isolation, not outer rollback. 0C.1 must have explicit approve/override regression tests. 0G must
> prove upgrade → downgrade → upgrade AND a fresh ingestion. 0A must scan tracked files for the
> leaked credential. Ensure ingestion source rows are flushed before same-session validation.

**7 — Strategic scope control**
> Stop doing backend architecture work unless something breaks. We have spent enough time making
> the spine trustworthy. From here the biggest gains are dashboard, frontend, demo flow, README, AI
> development log, final integration testing.

**8 — Frontend handoff**
> Generate a template and on it I'll use Vercel v0 AI for refinement in looks. Make the frontend
> specification concrete enough to hand to the frontend generator: screens, role-based navigation,
> each workflow, exact API endpoints each screen uses, request/response expectations, which backend
> endpoints are still missing.

**9 — AI evaluation design**
> Audit the current AI behaviour and create a small pragmatic evaluation plan across ~5–8
> representative exception types, not just the source-conflict hero case. For each: expected
> recommendation, what evidence should support it, and what would count as a bad/hallucinated
> result. Give a scoring rubric and the minimum number of real Groq calls.

**10 — Honest documentation**
> Rewrite README based strictly on the CURRENT project… **Do not invent anything or describe stale
> architecture.** Cross-check README, architecture and the actual code and list any remaining
> contradictions.

---

## 5. Human review process

**Architecture review** — structure, roles, lifecycle and the AI safety model were decided before
implementation. Agents were told not to redesign architecture or add abstraction.

**Code review** — generated changes were checked for scope creep, circular imports, incorrect
SQLAlchemy relationships, transaction boundaries, authorization, mutation paths, stale assumptions
and API contract mismatches.

**Test review** — the highest-value check. Tests were interrogated for whether they could actually
fail if the invariant broke. Negative controls were deliberately injected to prove non-vacuity.

**Evidence review** — AI outputs were checked against the actual EvidencePacket, not judged on
whether they sounded plausible.

**Scope review** — the agent was told to stop at each stage. Later stages never started
automatically, which localized failures and prevented cross-step drift.

**Final integration review** — the real API, real frontend and live Groq path were exercised after
isolated tests were green.

---

## 6. AI output that was rejected or corrected

### 6.1 A migration fix that broke the other database
The initial migration created `loans` with an inline foreign key to `loan_sources.id` *before*
`loan_sources` existed — invisible on SQLite, fatal on PostgreSQL.

The first fix used `op.create_foreign_key()` after both tables existed. Running it immediately
failed:

```
NotImplementedError: No support for ALTER of constraints in SQLite dialect
```

So the fix repaired PostgreSQL and broke every local dev and test database. It was replaced with
`op.batch_alter_table()`, which is portable, then proven with
`upgrade → downgrade → upgrade → real ingestion`.

**Lesson:** a fix verified only by reading is not verified. ORM metadata behaviour and imperative
migration scripts are not interchangeable, and "fixed" for one dialect can mean "broken" for
another.

### 6.2 A test that passed against a bug it was supposed to catch
An atomicity test for the AI disposition flow was written to prove that a mid-operation failure
rolls the whole thing back. To confirm it was not vacuous, a `db.commit()` was deliberately injected
mid-operation — **and the test still passed.**

The injection had been placed *after* `_apply_corrections`, so the simulated revalidation failure
fired before ever reaching it. Re-injecting at the true partial-commit boundary — inside
`edit_exception_field`, immediately before revalidation — made the test fail with exactly the right
diagnostic:

```
assert (82000.0, 'open', 17, 1, 0) == (95000.0, 'open', 17, 0, 0)
```

*Correction to an earlier draft of this log:* the implementation itself was **never** broken. The
disposition flow was atomic by construction — a single `db.flush()` in the service and one
`db.commit()` at the route. What was broken was the *test*, and had the first green control been
accepted, the suite would have advertised a guarantee it was not actually checking.

**Lesson:** a green test is not evidence until you have watched it fail for the right reason.

### 6.3 A genuinely broken transaction boundary
Separately — and this *was* an implementation defect — `edit_exception_field` mutated the loan on
the request session and then called `validate_loan()`, which opened its **own** `SessionLocal`.
Revalidation therefore ran in a different transaction from the edit that triggered it, unable to
see uncommitted changes. SQLite's leniency hid it; PostgreSQL would not have.

`validate_loan_in_session(db, loan_id)` was introduced so ingestion and reviewer edits validate
inside the caller's transaction, making edit + revalidation + exception resolution one unit of work.

**Lesson:** "the tests pass" and "the transaction semantics are correct" are different claims.

### 6.4 A provider call that could never have worked
The first 7B implementation used `response_format={"type": "json_object"}` with a system prompt that
never contained the word *json*. Groq rejects that combination outright:

```
400 - 'messages' must contain the word 'json' … to use 'response_format' of type 'json_object'
```

Every call would have failed, in code that had never been executed against the real provider. It
was replaced with provider-level **JSON Schema** structured output plus Pydantic re-validation.

**Lesson:** an OpenAI-compatible SDK is not an OpenAI-compatible service. Probe the real provider.

### 6.5 Duplicate detection that flagged the product working correctly
Realistic multi-source demo data produced **20 false-positive exceptions** — over half the total.
`duplicate_loan_id` counted source rows across *all* files, so any loan appearing in both the loan
tape and a servicer update was flagged a critical duplicate. That is not a defect; it is the entire
purpose of the system.

Scoped to repeats within the primary tape, then the same class of error appeared on
`document_manifest`, where multiple rows per loan is the expected shape. Open exceptions dropped
from 38 to 18, all genuine.

**Lesson:** realistic data exposes business semantics that synthetic fixtures cannot.

### 6.6 A rubric that penalized the model for following its own spec
The first AI evaluation rubric capped confidence at 0.7 for `request_human_review` outcomes and
scored the model down for exceeding it. Six of eight cases were marked down.

But the system prompt defines confidence as **strength of evidence, not certainty of a fix** — and
for `balance_gt_principal` the evidence that a problem exists is arithmetically unambiguous. The
model was correct; the rubric was wrong. It was rewritten to flag only high confidence with *no
supporting citation*, which is confidence in nothing. Tellingly, the case where evidence genuinely
is thin (`missing_document_status`) is the one the model scored *lowest* at 0.55 — good calibration
that the original rubric had punished.

**Lesson:** when an evaluation disagrees with the system, the evaluation may be what is wrong.

### 6.7 A plausible correction that was refused by design
`interest_rate = 12.5` is out of range and `0.125` is the obvious human inference — but `0.125`
appears nowhere in the evidence. The grounding rule refuses any suggested value not present in that
field's canonical or source evidence, so such a correction is downgraded to `request_human_review`
rather than trusted. Across evaluation runs the model never proposed it.

**Lesson:** for a financial copilot, correctness is *evidence-grounded* correctness. A believable
answer is not a supported one.

---

## 7. AI in debugging and discovery

Some of the most valuable AI work was diagnosis, not generation:

- tracing mapper failures to mismatched `back_populates`
- finding the SQLite/PostgreSQL database-URL inconsistency
- recognizing that a column's type stopped a test reaching the validation layer
- diagnosing cross-session edit/revalidation behaviour
- discovering that the app never initialized itself from a fresh clone
- finding the missing CORS boundary before frontend integration
- detecting model/migration text-length drift (`comment_text` was `String(2000)` in the model but
  `String(500)` in the migration, with the API accepting 2000 — invisible on SQLite, fatal on
  PostgreSQL)
- proving the original 7B provider request was invalid
- diagnosing evaluation failures as a Groq **tokens-per-day** cap rather than model behaviour

Agents were strongest at repository-wide search, repetitive implementation, focused test writing,
and reducing a large codebase to narrow diagnostic hypotheses. Human judgment mattered most for
semantics, scope, security boundaries, and deciding whether a passing test meant anything.

---

## 8. AI-generated code estimate

**Roughly 70–80%** of the final codebase is AI-generated or AI-assisted. An exact figure is not
meaningful because many files were iteratively rewritten and corrected.

Included: implementation code, tests, schemas, routes, services, frontend components,
documentation drafts.

Human contribution: architecture and scope decisions, task decomposition, prompt design,
acceptance or rejection of approaches, interpretation of failures, security and transaction
decisions, live-provider verification, UI direction, and deciding what *not* to build.

---

## 9. AI evaluation of the shipped feature

Beyond building the AI, its behaviour was measured. `scripts/eval_ai.py` scores eight
representative exception types; `docs/ai_evaluation.md` holds the results.

The key insight reframed the whole exercise: because a suggested value must already appear in the
evidence, **only `source_conflict` can ground a correction in this dataset**. Every other rule type
should resolve to `request_human_review`. The evaluation therefore measures **conservatism, not
correction coverage** — a model proposing plausible fixes everywhere would be failing.

Results:

- **Zero hallucinations reached persisted output** in any run.
- **Two genuine fabrications caught and rejected**: a nonexistent `source_id=67`, and a citation to
  `validation.latest.details` (a packet path, not an evidence field). The guard is not theoretical.
- **25 runs of the demo case**: 68% proposed the correct value, 32% deferred, **0% proposed a wrong
  value** — never wrong, but not always willing.

That last figure is reported rather than tuned away. Forcing corrections would trade the safety
guarantee for a nicer demo.

---

## 10. Lessons learned

**Quantize large tasks.** Prompts mixing architecture, implementation, testing and future stages
were noticeably less reliable. Narrow steps made failures local and reversible.

**Define the invariant before writing the test.** A test must be able to fail. §6.2 is the clearest
example of false confidence from a superficially passing test.

**Real data exposes semantic bugs.** The engineered dataset revealed duplicate-detection errors that
isolated fixtures never would.

**Probe real providers.** Compatibility at the SDK layer is not compatibility in behaviour.

**Evidence beats plausibility.** A believable recommendation that is not traceable to supplied
evidence is not acceptable in this domain.

**Passing tests are not lifecycle integration.** Hundreds of green tests coexisted with an
application that could not serve a single authenticated request from a fresh clone. End-to-end
lifecycle tests were added as a separate evidence layer.

**Keep AI advisory.** The strongest design lets AI recommend and explain while mutation and final
authority stay in deterministic, auditable, human-controlled paths.

**Stop when the product is strong enough.** Repository-layer refactoring, predictive modelling
outside challenge scope, production-grade security and broad Postgres infrastructure were
deliberately skipped to protect time for the scored workflow, frontend, AI controls, documentation
and demo.

---

## 11. Outcome

```
CSV / source data → raw lineage → canonical loan → deterministic validation → exception
  → reviewer workflow → EvidencePacket → grounded AI recommendation → human disposition
  → revalidation → verified snapshot → SHA-256 → export → audit trail
```

Delivered: deterministic validation, source-level traceability, bounded provenance-aware AI
evidence, structured recommendations, citation grounding, reviewer-controlled mutation, immutable
verified records, cryptographic integrity hashes, complete audit history and role-specific
workflows.

The process itself demonstrates agentic coding discipline: small stages, explicit constraints,
focused tests, human review, rejection of unsafe or incorrect generated output, and repeated
verification against the running application.

---

## 12. Deliverable status

| Deliverable | Status |
|---|---|
| GitHub repository with source | ✅ Pushed |
| Working application (backend + frontend) | ✅ Both run; verified together against live API |
| README with setup, env vars, run commands | ✅ Every claim verified against code |
| Architecture note | ✅ Rewritten to match shipped system; route table diffed against live OpenAPI |
| **AI Development Log** | ✅ This document |
| Test credentials for all three roles | ✅ Documented in README and on the login screen |
| Sample verified loan dataset | ⏳ To finalize |
| Audit trail export | ⏳ To finalize |
| Demo video (≤5 min) | ⏳ Remaining |

---

## 13. Note on honesty

This log records unsuccessful AI-assisted work alongside successful work. Two entries in §6 exist
only because a green result was distrusted and re-examined, and one entry corrects an earlier draft
of this very document that overstated a defect.

The useful pattern throughout was:

> **AI proposes → human challenges → tests prove → the implementation survives or changes.**

That produced a more reliable system than either fully manual implementation or unrestricted
autonomous coding would have.
