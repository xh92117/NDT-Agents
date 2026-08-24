# S5-07 API Management Evidence

**Run ID:** `S5-07-API-MANAGEMENT-20260824-01`

**Status:** `PASS` for the isolated control plane; full S5-07 remains `BLOCKED`

**Branch:** `codex/s5-07-api-management`

**Base commit:** `2597319ce8242c515429db86cf6dc764dc233381`

**Configuration SHA-256:** `689e4cf225d8ca4730e21a71479775d1266194d61223840461927b284d44d16a`

## Scope

This run covers the isolated, configuration-only provider and model registry scaffold. It does not
perform physical model inference, resolve an API key, approve DeepSeek for production, or complete
the unfinished S5-01 and S5-06 dependencies.

## Implemented result

- `ndt_agents.models` adds strict provider, endpoint, model, compliance, binding, selection, and
  resolved-route contracts with unknown-field rejection.
- Registry publication hashes catalog and binding content deterministically and rejects duplicate,
  stale, cross-scope, disabled, unauthorized, network-denied, data-ineligible, capability-missing,
  token-excess, and production-ineligible routes with typed next actions.
- Multiple independent bindings have separate secret references, defaults, and fallbacks. Binding
  order does not change the registry hash.
- Every successful or denied resolution produces one hash-only S1-10 `MODEL` audit event.
- The DeepSeek V4 catalog records the official OpenAI-compatible endpoint and the current Pro,
  Flash, and experimental vision model IDs. It contains no credential value and is restricted to
  public or synthetic personal-development data.

## Immutable configuration artifacts

| Artifact | SHA-256 |
|---|---|
| `config/model-providers/deepseek-v4.v1.json` | `7eb570adb12b029a4995b77e39813a534a89109fe92e2f13ef09f1a344f01fef` |
| `architecture/personal-development-runtime.v1.json` | `d77fc516704d4d0dd5e91e61de5432e6cf800bded956b8aec6b1b78cbadb22bb` |

The configuration hash above covers the model package exports and implementation, DeepSeek
catalog, dedicated tests, personal runtime candidate, and Model API Registry V1 contract.

## Test execution

Environment: local Windows 11, CPython 3.12.13, uv 0.11.20. The full test run started at
2026-08-24T13:54:49+08:00 and ended at 2026-08-24T13:54:53+08:00.

| Check | Result |
|---|---|
| `uv run pytest tests/models/test_model_api_registry.py -q` | PASS, 14 dedicated tests |
| `uv run pytest -q` | PASS, 253 tests |
| four controlled generators and tracked-output review | PASS, zero generated drift |
| `uv run ruff check src tools tests` | PASS |
| `uv run ruff format --check src tools tests` | PASS, 82 files formatted |
| `uv run mypy` | PASS, 82 source files, zero issues |
| `uv run python tools/check_controlled_docs.py` | PASS, DOC 1.30, four ASCII files, seven gates |
| `PYTHONUTF8=1 uv run pip-audit --local --progress-spinner off` | PASS, no known vulnerabilities |
| `git diff --check` | PASS |

The configuration and test paths import no provider HTTP client and make zero physical DeepSeek
calls. No API key was requested, received, stored, logged, or serialized.

## Remaining blockers

- S5-01 must connect model inference to the shared Tool Registry, S1-08 budget guard, timeout and
  retry accounting, typed provider failures, and evidence capture.
- S5-06 and later professional workflows must define canonical inspection-data boundaries before a
  model can interpret inspection evidence.
- DeepSeek processing/storage region, retention, training use, commercial/exit terms, pricing,
  quota, and exact live account eligibility remain unverified.
- A scoped secret reference and approved local secret-provider adapter do not yet exist. A live
  synthetic `PROVIDER-SMOKE` is therefore not authorized or run.
- Production, confidential/restricted data, formal conclusions, and commercial use remain blocked.
