# S6-02-PRO-APP Evidence

## Scope

- Task: `S6-02-PRO-APP`
- Branch: `codex/s6-02-professional-app`
- Data: deterministic SYNTHETIC input only
- Provider, network, and tool calls: forbidden in this application slice
- Formal use: forbidden

## Implemented boundary

- The authenticated Web workbench routes G0 to the existing General executor and P1 to one new
  application-owned professional executor.
- P1 selection is deterministic and server-owned: one `technical_qa` assignment only.
- The child receives one same-scope minimal context with no artifacts or tools.
- The existing configured reviewed orchestration runtime owns professional execution, independent
  per-result review, review-manifest creation, and reviewed-professional Main aggregation.
- Success requires explicit `REVIEW_REQUIRED` and review-complete events before `SUCCEEDED`.
- P2, P3, K1, arbitrary agent selection, customer data, live providers, tools, formal use,
  approval, publication, and production eligibility remain excluded.

## Verification

- Dedicated P1 success, idempotent replay, manifest, review-conflict, non-P1 denial, and combined
  G0/P1 routing tests plus existing General Web and configured review runtime tests: PASS, 25 cases.
- Complete repository regression: PASS, all 1146 collected cases with one documented Windows skip.
- Ruff check: PASS.
- Ruff format check: PASS over 215 files.
- Strict mypy: PASS over 215 source files.
- Controlled documentation: PASS at version 1.92.
- Diff check: PASS.
- Code graph: refreshed against base commit and the active branch changes.
- Convergence audit: PASS with no blocking duplicate path or Review bypass. Static graph test
  mapping did not associate the dynamic FastAPI tests with the executor methods; direct source and
  passing test verification confirmed the G0/P1 route, professional execution, review success,
  review conflict, and non-P1 denial coverage.
- Physical model/network/tool calls: 0 / 0 / 0.

The first complete regression correctly rejected the planned evidence link before this file
existed. After creating the evidence file, the controlled-document check and complete regression
were rerun and passed.

## Current status

`PASS`: S6-02-PRO-APP is complete for the deterministic SYNTHETIC P1 Technical QA Web path. Live
professional and Review Agent model delegates, correction qualification, customer data, tools,
formal use, desktop grants, production eligibility, immutable CI, and release remain excluded.
