# S6-02 Web Agent Acceptance Evidence

## Result

`PASS` for the covered local Web agent behaviors on the mutable branch
`codex/s6-02-live-professional` at base commit
`0cd079b50c0bc8af59ad98469e0f35af94280fb2`.

This result is limited to deterministic offline SYNTHETIC acceptance. It is not live-provider,
production identity, distributed recovery, customer-data, formal-use, publication, release, or
desktop evidence.

## Candidate and environment

- Date: 2026-08-28.
- Host: local Windows.
- Python: CPython 3.12.13.
- Dependency runner: uv 0.11.20.
- Browser behavior runtime: Node.js 24.19.0.
- Browser: Codex in-app browser against `http://127.0.0.1:8766`.
- Scenario catalog: `config/acceptance/web-agent.v1.json`, schema and catalog version 1.0.0.
- Provider: injected `OfflineAcceptanceProvider`; physical external network calls: 0.
- Input: two fixed SYNTHETIC browser tasks only.

## Implemented acceptance boundary

- `tools/web_agent_acceptance.py` validates a strict duplicate-key-denying, UTF-8, size-bounded
  scenario catalog and composes the production local Web application with an injected deterministic
  provider.
- The loopback runner accepts only the two fixed G0 and P1 SYNTHETIC request bodies. Changed input is
  denied with `ACCEPTANCE_SYNTHETIC_REQUEST_REQUIRED` and a stable next action before provider use.
- The provider emits the existing General, Technical QA, and Review Agent result schemas. It has no
  tool or network adapter and reports zero physical network calls.
- The sanitized evidence endpoint exposes only aggregate call counts and safety state and uses
  `Cache-Control: no-store`.

## Versioned scenario outcomes

| Scenario | Expected and observed outcome | Provider calls |
|---|---|---:|
| `g0_success` | `ACCEPTED -> RUNNING -> SUCCEEDED` | General 1 |
| `p1_success` | `ACCEPTED -> RUNNING -> REVIEW_REQUIRED -> RUNNING -> SUCCEEDED` | Technical QA 1, Review 1 |
| `p1_review_conflict` | terminal `REVIEW_CONFLICT` failure | Technical QA 1, Review 1 |
| `p1_malformed_review` | terminal `REVIEW_EXECUTION_FAILED` failure | Technical QA 1, Review 1 |
| `g0_malformed_output` | terminal `MODEL_OUTPUT_SCHEMA_INVALID` failure | General 1 |
| `g0_provider_failure` | terminal `MODEL_PROVIDER_UNAVAILABLE` failure | General 1, retry 0 |
| `p1_budget_denial` | `BUDGET_ACTIVE_LIMIT_EXCEEDED` before inference | 0 |
| `p1_restart_replay` | reviewed P1 terminal state and events replay after SQLite reopen | initial 2, replay 0 |
| `authorization_denial` | `AUTH_TOKEN_MISSING` before inference | 0 |
| `cross_scope_denial` | `CLIENT_TASK_NOT_FOUND` without task disclosure | 0 |
| `browser_g0_success` | rendered successful rules path and formal-use denial | General 1 |
| `browser_p1_success` | rendered Review Passed, Main result, and formal-use denial | Technical QA 1, Review 1 |

Every scenario required zero physical tool calls, zero external network calls, and
`formal_use_allowed=false`. Terminal idempotency replay made zero additional provider calls.

## Real browser evidence

The in-app browser entered through `/local/workbench/session` and was redirected to the same
production-composed `/workbench` UI.

- Fixed G0 task `efd2d34b-c1f8-4974-8eed-8c5cff5d5fba` rendered `SUCCEEDED`, `Rules path`,
  `Not allowed`, and exactly three ordered events.
- Fixed P1 task `871e250b-5556-4d1c-9ade-536cfadc6639` rendered `SUCCEEDED`, `Passed`,
  `Not allowed`, and exactly five ordered events including `REVIEW_REQUIRED` and independent Review
  `RUNNING` before the terminal result.
- A changed P1 goal was denied in the page with `ACCEPTANCE_SYNTHETIC_REQUEST_REQUIRED`, the bounded
  message, and `Use one fixed G0 or P1 acceptance case.` No provider call was added.
- The responsive viewport override produced no document-level horizontal overflow.
- Browser console warnings and errors: 0.
- Final aggregate provider evidence: calls 3; General 1; Technical QA 1; Review 1; external network 0;
  physical tools 0; formal use false.
- The loopback service was stopped after capture. No resubmission, retry, fallback, correction,
  customer data, publication, release, or desktop action occurred.

## Reproducible verification

The following commands passed in the stated environment:

```text
uv run python tools/web_agent_acceptance.py
uv run pytest tests/client/test_web_agent_acceptance.py -q
uv run pytest tests/client/test_web_agent_acceptance.py tests/client/test_web_stability.py tests/client/test_async_workbench.py tests/client/test_sqlite_workbench_repository.py tests/client/test_web_workbench.py tests/client/test_general_model_workbench.py tests/client/test_professional_workbench.py tests/orchestration/test_professional_model_delegate.py tests/orchestration/test_budget.py tests/security/test_platform_security.py -q
node --test tests/client/web-workbench.test.js
uv run pytest -q
uv run ruff format --check .
uv run ruff check .
uv run mypy
uv run python tools/check_controlled_docs.py
git diff --check
code-review-graph update --repo "D:\program flies\...\NDT Agents"
code-review-graph status --repo "D:\program flies\...\NDT Agents"
```

Results before final controlled-document synchronization:

- Acceptance file: 13 passed.
- Affected Python profile: 104 passed.
- Browser behavior tests: 7 passed.
- Complete repository collection: 1,202 tests; final run result is recorded in the synchronized test
  log.
- Ruff: 449 files already formatted; all checks passed.
- Strict mypy: 225 source files; no issues.
- Code graph: 241 files, 4,107 nodes, and 37,615 edges on the stated branch and base commit. The new
  untracked acceptance artifacts were also reviewed directly because they are outside the committed
  graph snapshot.

## Convergence review

The acceptance harness is a development-only loopback composition around the existing production
application factory, not a second product execution path. It does not import test helpers, modify the
runtime route, or expose another provider/tool authority. The fixed-request middleware is specific to
the runner and prevents the broader live-runner input surface from being reused here. Direct source,
configuration, test, browser, and complete-regression evidence found no actionable redundant or
unreachable path in this task scope.

## Residual limits

This mutable local PASS does not qualify a live model provider, production identity or storage,
multi-host coordination, provider idempotency after unknown remote outcome, proxy/load behavior,
customer data, a formal conclusion, publication, desktop packaging, immutable CI, or release.
Desktop task `S6-02` remains paused until the user explicitly reprioritizes it.
