# Phased Implementation Plan — Vera Bot

Six independently-testable phases, each adding meaningful capability. Build them in order; do not skip phases.

| # | Phase | What it delivers | Pass criterion | Effort |
|---|---|---|---|---|
| 1 | [HTTP Foundation & State](phase-01-http-foundation.md) | All 5 endpoints reachable; idempotent versioned context store | `judge_simulator.py warmup` passes | 4–6 h |
| 2 | [LLM Composer Baseline](phase-02-llm-composer.md) | `/v1/tick` produces real LLM-composed messages | `phase2_short` returns ≥1 scored action | 6–8 h |
| 3 | [Composition Quality](phase-03-composition-quality.md) | Voice packs, trigger framings, validation, suppression | `full_evaluation` avg ≥ 35/50 | 10–14 h |
| 4 | [Reply Handler](phase-04-reply-handler.md) | Multi-turn `/v1/reply` with intent classifier | `auto_reply_hell`, `intent_transition`, `hostile` all pass | 10–12 h |
| 5 | [Customer-Facing & Edge Cases](phase-05-customer-edge-cases.md) | `merchant_on_behalf` flow, consent gate, expiry, version updates | Customer-scope triggers produce valid actions; `full_evaluation` avg ≥ 38/50 | 8–10 h |
| 6 | [Submission & Deployment](phase-06-submission-deployment.md) | `submission.jsonl`, README, public deployment | E2E from public URL passes; avg ≥ 38/50 | 6–8 h |

**Total estimated effort**: 44–58 hours of focused work.

---

## How to use these documents

Each phase document follows the same structure:

1. **Goal** — one sentence describing what changes after this phase
2. **Why this phase next** — the strategic ordering rationale
3. **Capabilities Delivered** — bulleted feature list
4. **Files / Modules to Implement** — concrete files with code sketches
5. **Test Plan** — unit, integration, and judge-simulator tests
6. **Expected Output** — sample request/response pairs showing what "done" looks like
7. **Dependencies (prior phases)** — what must be done first
8. **Acceptance / Definition of Done** — checklist to confirm the phase is complete

---

## Architecture Reference

For the full system design (component diagram, data flows, module layout, tech stack), see [`../architecture.md`](../architecture.md).

For the functional spec (problem statement, requirements, edge cases), see [`../vera-bot.md`](../vera-bot.md).

---

## Recommended workflow

1. **Read the spec + architecture first** — don't skip to phase docs.
2. **Tackle one phase at a time** — finish all acceptance criteria before moving on.
3. **Don't skip the tests** — judge_simulator.py is the same harness the actual judge uses.
4. **Commit at phase boundaries** — `git tag phase-1-complete`, `phase-2-complete`, etc., so you can roll back if a later phase introduces regressions.
5. **After Phase 3**, score quality regularly — composition is the biggest scoring lever; small prompt changes can swing average scores by 5+ points.
6. **Don't deploy until Phase 6** — Phases 1–5 are validated locally with `judge_simulator.py`. The public URL is a Phase 6 concern.
