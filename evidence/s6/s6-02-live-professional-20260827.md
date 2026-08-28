# S6-02-PRO-LIVE Professional and Review Model Evidence

## Status

`LIVE_PASS_SYNTHETIC_NON_PRODUCTION` on branch `codex/s6-02-live-professional`, based on commit
`0cd079b` plus the recorded mutable working-tree change. This is passing mutable local live-provider
smoke evidence, not immutable PR, production, formal-use, or release evidence.

## Scope

This record captures the default-off local Technical QA and independent Review Agent model
composition, deterministic injected-provider tests, security and budget boundaries, complete
regression, and any separately acknowledged fixed SYNTHETIC live smoke for S6-02-PRO-LIVE.

The operator separately authorized one fixed SYNTHETIC P1 smoke with at most two DeepSeek network
calls and no retry, fallback, tools, correction, customer data, formal conclusion, or publication.

## Implemented boundary

- `NDT_PROFESSIONAL_MODEL_DELEGATE_ENABLED` is default off and requires the already validated local
  General delegate, complete model, prompt, and agent configuration, and exact provider-policy
  acknowledgement.
- Only `general` and `technical_qa` receive model delegates. Every other professional profile uses
  the existing denied delegate, and all model-driven correction executors fail closed.
- Technical QA accepts only a no-tool, no-artifact, P1 professional child and returns a strict
  non-formal AgentResult with no artifact or evidence output.
- Review accepts only the exact read-only Technical QA result and returns PASS, CONFLICT,
  HUMAN_REQUIRED, or FAILED. REVISE is excluded because correction is not qualified.
- Technical QA reserves at most 3,600 input plus 2,400 output tokens. Review reserves at most 3,000
  input plus 1,000 output tokens. The combined 10,000-token reservation equals the unchanged P1
  active limit. Both requests disable fallback, retry, tools, formal use, and direct user delivery.
- P1 success still requires the existing review manifest and reviewed-professional Main aggregation.

## Verification

Environment: local Windows, CPython 3.12.13, uv 0.11.20, deterministic injected provider, fixed
SYNTHETIC inputs, and zero physical model or network calls.

| Check | Command or method | Result |
|---|---|---|
| Dedicated delegate tests | `uv run pytest tests/orchestration/test_professional_model_delegate.py -q` | PASS, 6 tests |
| Affected runtime tests | local Workbench, General, deterministic professional, configured review, and new delegate suites | PASS, 35 tests |
| Complete regression | `uv run pytest -q` plus collection count | PASS, all 1156 collected tests; one documented Windows skip because control-character filenames are unavailable |
| Format | `uv run ruff format --check src tools tests` | PASS, 219 files |
| Lint | `uv run ruff check src tools tests` | PASS |
| Type safety | `uv run mypy src tools tests --strict` | PASS, 219 source files |
| Controlled docs | `uv run python tools/check_controlled_docs.py` | PASS, version 1.94, four ASCII files, seven gates |
| Clean startup | local model, prompt, agent, environment, General, professional, Workbench, and exact policy settings with `uv run ndt-agents --check` | PASS; professional mode true and all Workbench routes mounted with zero provider calls |
| Budget stop | lowered the exact Technical QA active total-token limit to 5,999 | PASS; `BUDGET_ACTIVE_LIMIT_EXCEEDED` before the injected provider, zero calls |
| Review stops | injected CONFLICT and malformed review outputs | PASS; both stopped before Main aggregation with no success event or review manifest |
| Code graph | staged source graph update at the exact repository root | PASS; new delegate and test nodes indexed |
| Convergence audit | audit mode, convergence focus over configuration, application assembly, delegates, schemas, tests, and entry points | PASS with no blocking or warning finding |
| Diff integrity | `git diff --check` | PASS; one informational Git line-ending notice only |

The convergence audit observed that the hosted profile and request assembly intentionally parallel
the existing General delegate. They have different typed outputs, token reservations, context
checks, and review behavior, so this is not a second authority for one business rule. Keep the
separate adapters for the current two-route slice and reconsider a shared internal call builder if
a third model-backed agent route is introduced.

## Acknowledged live attempt

- Browser-created task: `972eb2fe-b4ef-48ef-9370-80381012509f`.
- Fixed route and data: P1 Technical QA, SYNTHETIC limitations only.
- Ordered events: `ACCEPTED`, `RUNNING`, `FAILED`.
- Request duration: approximately 45.45 seconds.
- Review events and Review Agent execution: none observed.
- Main aggregation, tools, correction, retry, fallback, formal use, and publication: none.
- Loopback service: stopped after the single submission; no resubmission occurred.

The Technical QA path stopped before producing a reviewable result. The authenticated JSON evidence
endpoint returned HTTP 200, but the browser safety layer refused direct JSON navigation and did not
retain the response body. Therefore the exact provider failure code, returned token counts, finish
reason, and physical-call counters are unavailable and must not be inferred as durable evidence.
The bounded runtime permits only one provider attempt in this stage, and no Review Agent call began.

## Offline evidence-view repair

The runner now accepts only the fixed P1 request, enables the professional model delegate, reports
separate professional and review delegate counts, sums only sanitized provider counters, and exposes
the same payload through an authenticated, no-store HTML view. The view contains no model output or
secret. Two injected-provider runner tests pass, including exact two-call success, idempotent replay,
changed-input denial, and HTML evidence rendering. The complete 1156-case regression passed with the
one documented Windows control-character filename skip; Ruff, format over 219 files, strict mypy
over 219 source files, DOC 1.95, and diff checks also passed. No additional DeepSeek call was made.

## Acknowledged revalidation

- Browser-created task: `cee56e69-f513-4edf-8037-ab6825b5880b`.
- Ordered events: `ACCEPTED`, `RUNNING`, `FAILED`.
- Request duration: approximately 43.35 seconds.
- Professional failure: `MODEL_INCOMPLETE`.
- Provider/model/snapshot: `deepseek` / `deepseek-v4-pro` / `DeepSeek-V4-Pro-0813`.
- Input/output tokens: 3,492 / 2,400.
- Finish reason: `length`.
- Professional/Review delegate calls: 1 / 0.
- Physical LLM/network/tool calls: 1 / 1 / 0.
- Review completion, retry, fallback, correction, and Main aggregation: none.
- Formal-use candidate and secret output: false.
- Loopback service: stopped after evidence capture; no resubmission occurred.

The authenticated HTML view captured the exact failure dimension: the Technical QA output reached
its 2,400-token reservation. No Review Agent call began because no complete professional result was
available.

## Bounded brevity correction

The token and call budgets remain unchanged. The internal Technical QA result schema now limits the
summary to 600 characters, observations to at most three items of 300 characters, limitations to at
most three items of 300 characters, and the next action to 300 characters. This preserves the
required synthetic limitations while removing the former allowance for a 2,000-character summary
and two lists of up to six 500-character items. Eight focused professional and runner tests pass,
including exact schema bounds, two-call reviewed aggregation, denial paths, and evidence rendering.
The complete 1156-case regression passed with the one documented Windows control-character filename
skip; Ruff, format over 219 files, strict mypy over 219 source files, DOC 1.96, and diff checks also
passed. No additional DeepSeek call was made.

## Narrowed-schema revalidation

- Browser-created task: `c15634ac-bbaa-41eb-bccc-b8407b757a86`.
- Ordered events: `ACCEPTED`, `RUNNING`, `FAILED`.
- Request duration: approximately 39.60 seconds.
- Professional failure: `MODEL_INCOMPLETE`.
- Input/output tokens: 3,493 / 2,400.
- Finish reason: `length`.
- Professional/Review delegate calls: 1 / 0.
- Physical LLM/network/tool calls: 1 / 1 / 0.
- Review completion, retry, fallback, correction, and Main aggregation: none.
- Loopback service: stopped after evidence capture; no resubmission occurred.

The narrowed JSON Schema alone did not reduce the provider response. Offline inspection then found
that Technical QA system prompt 1.1.0 unconditionally required `TechnicalQACandidate@1.0.0`, while
the live delegate response contract required `AgentResult`.

## Bounded prompt correction

Technical QA prompt 1.2.0 now requires the exact schema supplied in `response_contract`, targets a
complete JSON response within 1,200 completion tokens, prefers minimum list cardinality, and forbids
schema or limitation repetition. Its hash and runtime prompt version are updated together. The
2,400 maximum output, all task budgets, model identity, tools, retry, fallback, and formal-use
boundaries remain unchanged. Forty-four focused prompt, agent-configuration, professional, and
Technical QA tests pass. The complete 1156-case regression passed with the one documented Windows
control-character filename skip; Ruff, format over 219 files, strict mypy over 219 source files,
DOC 1.97, and diff checks also passed. No additional DeepSeek call was made.

## Prompt-aligned live revalidation

- Browser-created task: `3e527ddf-0acc-4546-8051-39cd0b6f9983`.
- Ordered events: `ACCEPTED`, `RUNNING`, `REVIEW_REQUIRED`, `FAILED`.
- Request duration: approximately 41.54 seconds.
- Professional failure: none.
- Review failure: `BUDGET_TOKEN_RESERVATION_EXCEEDED`.
- Provider/model/snapshot: `deepseek` / `deepseek-v4-pro` / `DeepSeek-V4-Pro-0813`.
- Combined input/output tokens: 7,706 / 2,766.
- Finish reasons: `stop`, `failed`.
- Professional/Review delegate calls: 1 / 1.
- Physical LLM/network/tool calls: 2 / 2 / 0.
- Review completion, retry, fallback, correction, and Main aggregation: none.
- Formal-use candidate and secret output: false.
- Loopback service: stopped after evidence capture; no resubmission occurred.

Technical QA completed within its reservation and produced the first reviewable live professional
result. The independent Review Agent then exceeded its unchanged 4,000-token reservation. The two
permitted DeepSeek calls were consumed exactly; no further network call was made under this
acknowledgement.

## Bounded review-context correction

The Review Agent request now receives a compact model-visible context containing only exact task,
target-run, target-hash, context-manifest, scope, reviewer, checklist, read-only, delivery, and
correction-count bindings. Complete internal review state remains in the deterministic runtime and
audit boundary. Review prompt 1.2.0 follows the supplied response contract, forbids decisions absent
from its enum, targets complete JSON within 300 completion tokens, and limits findings to three
concise blocking items. The 3,000-input, 1,000-output, 4,000-review, and 10,000-total reservations,
model identity, tool, retry, fallback, correction, and formal-use boundaries remain unchanged. No
DeepSeek call was made for this correction.

Sixty-five focused review, prompt, professional, and compatibility tests pass. The complete 1,156-case
regression passes with the one documented Windows control-character filename skip. Ruff, format over
440 files, strict mypy over 219 source files, DOC 1.98, diff checks, and the incremental code-graph
refresh pass. The verified graph contains 241 files, 4,047 nodes, and 37,054 edges with no build error.

## Compact-context live revalidation

- Browser-created task: `ef9bf0fe-b3fb-4ed9-b5fb-1c5f3990e590`.
- Ordered events: `ACCEPTED`, `RUNNING`, `REVIEW_REQUIRED`, `FAILED`.
- Request duration: approximately 58.49 seconds.
- Professional failure: none.
- Review failure: `BUDGET_TOKEN_RESERVATION_EXCEEDED`.
- Provider/model/snapshot: `deepseek` / `deepseek-v4-pro` / `DeepSeek-V4-Pro-0813`.
- Combined input/output tokens: 7,587 / 3,164.
- Finish reasons: `stop`, `failed`.
- Professional/Review delegate calls: 1 / 1.
- Physical LLM/network/tool calls: 2 / 2 / 0.
- Review completion, retry, fallback, correction, and Main aggregation: none.
- Formal-use candidate and secret output: false.
- Loopback service: stopped after evidence capture; no resubmission occurred.

Technical QA again completed and entered mandatory independent review. Compacting the non-target
review context reduced combined input by 119 tokens compared with the prior live run, but Review
still exceeded its unchanged reservation. Combined output increased by 398 tokens. Aggregate
evidence does not identify the exact per-stage input and output split, so a further budget or payload
change would be speculative. The two-call authorization was consumed exactly and no further model
call was made.

## Provider-visible canonical projection correction

Offline request measurement showed that the Review provider prompt still duplicated the complete
6,523-character canonical dataset. The prior context correction changed only 119 combined live input
tokens because the canonical dataset dominated the Review prompt. ModelInference contract 1.1.0 now
adds a hash-bound prompt mode that defaults to `FULL`. Technical QA remains full. Review selects
`IDENTITY_ONLY`, containing only schema version, dataset ID, exact scope, synthetic origin, method
code, and manifest hash. The full canonical dataset is still validated before the provider call and
remains bound in gateway evidence and audit.

The Review canonical prompt contribution is 464 characters and its complete user payload is 3,954
characters in the deterministic request probe. The Technical QA canonical payload remains 6,523
characters and its user payload remains 8,659 characters. The runner now exposes input tokens,
output tokens, and finish reason separately for Technical QA and Review while preserving aggregate
counters. Seventy-nine focused provider, gateway, delegate, and runner tests pass. The complete
repository run collected 1,157 tests and passed with one documented Windows skip. Ruff, formatting
over 440 files, strict mypy over 121 source files, DOC 2.00, and diff checks also pass. No DeepSeek
call was made during this correction.

## Final projection-corrected live revalidation

- Browser-created task: `c8757c8b-e135-46ef-8f0a-80a7920da93a`.
- Ordered events: `ACCEPTED`, `RUNNING`, `REVIEW_REQUIRED`, `FAILED`.
- Request duration: approximately 49.15 seconds.
- Professional failure: none.
- Review failure: `MODEL_INCOMPLETE`.
- Provider/model/snapshot: `deepseek` / `deepseek-v4-pro` / `DeepSeek-V4-Pro-0813`.
- Technical QA input/output/finish: 3,562 / 1,929 / `stop`.
- Review input/output/finish: 1,779 / 1,000 / `length`.
- Combined input/output tokens: 5,341 / 2,929.
- Professional/Review delegate calls: 1 / 1.
- Physical LLM/network/tool calls: 2 / 2 / 0.
- Review completion, retry, fallback, correction, and Main aggregation: none.
- Formal-use candidate and secret output: false.
- Browser and loopback service: closed after evidence capture; no resubmission occurred.

The identity projection reduced Review input below its unchanged 3,000-input reservation and closes
the R-014 input-reservation defect. Review then reached its exact 1,000-output-token cap and ended
with finish reason `length`, exposing R-015. The authorization was consumed exactly. No repair or
additional DeepSeek call was made, and the failed result was not aggregated or used formally.

## Review thinking-mode offline correction

The DeepSeek V4 Chat Completions contract enables thinking by default. Its `completion_tokens`
includes reasoning tokens, and the response exposes reasoning separately from final content. The
application adapter omitted the thinking control, so the final Review run could consume the exact
1,000-token completion reservation before finishing the typed JSON even though its instruction
targeted a 300-token response.

ModelInference contract 1.2.0 adds a hash-bound provider-neutral reasoning mode. The default omits
an override and preserves Technical QA and existing callers. Review alone selects `DISABLED`; the
DeepSeek adapter emits exactly `thinking: {type: disabled}`. No arbitrary provider parameters are
accepted, and the 3,000-input, 1,000-output, 4,000-Review, and 10,000-total limits are unchanged. No
DeepSeek model call was made during this correction.

The final offline run passed 118 affected provider, gateway, orchestration, review, runner, and Web
tests. The complete repository run collected 1,159 tests and passed with one documented Windows
skip. Ruff, formatting over 440 files, strict mypy over 121 source files, DOC 2.02, and staged and
unstaged diff checks passed.

## Thinking-off live revalidation

- Browser-created task: `935882cd-0a19-4f70-835a-c6317d123f1a`.
- Ordered events: `ACCEPTED`, `RUNNING`, `REVIEW_REQUIRED`, review `RUNNING`, `SUCCEEDED`.
- Request duration: approximately 41.74 seconds.
- Professional and Review failures: none.
- Provider/model/snapshot: `deepseek` / `deepseek-v4-pro` / `DeepSeek-V4-Pro-0813`.
- Technical QA input/output/finish: 3,552 / 2,059 / `stop`.
- Review input/output/finish: 1,719 / 240 / `stop`.
- Combined input/output tokens: 5,271 / 2,299.
- Professional/Review delegate calls: 1 / 1.
- Physical LLM/network/tool calls: 2 / 2 / 0.
- Review required and completed: true / true.
- Retry, fallback, and correction: none.
- Formal-use candidate and secret output: false.
- Browser and loopback service: closed after evidence capture; no resubmission occurred.

The Review-only thinking-off control kept the complete typed Review result within its unchanged
1,000-output reservation. Independent review passed the exact professional manifest, and Main
aggregation returned only the synthetic, non-production, non-formal limitations. R-015 and
S6-02-PRO-LIVE are closed. No customer data, tool, formal conclusion, publication, production
action, or release was enabled.

## Current boundary

S6-02-PRO-LIVE is `DONE` for this mutable local SYNTHETIC scope. R-015 is closed. Any later provider
call still requires a new exact acknowledgement.
Provider policy, customer data, formal use, publication, production, immutable CI, and release
remain out of scope.
