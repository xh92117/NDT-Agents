# S5-07 Model Configuration Bootstrap Evidence

**Run ID:** `S5-07-CONFIG-BOOTSTRAP-20260824-01`

**Status:** `PASS_ISOLATED_BOOTSTRAP`; full S5-07 remains `BLOCKED`

**Branch:** `codex/s5-07-model-config-bootstrap`

## Scope

This run covers the isolated YAML/environment startup bootstrap, local read-only environment secret
adapter, typed application-state assembly, and non-secret readiness status. It does not execute a
physical model call or complete S5-01, S5-06, or the full S5-07 inference path.

## Implemented boundary

- `NDT_MODEL_CONFIG` selects one bounded strict YAML document and validated relative catalogs;
- `NDT_MODEL_ENV_FILE` explicitly selects a bounded ignored UTF-8 literal environment file;
- process environment values override file values and only referenced variables are retained;
- enabled bindings require a present secret while disabled bindings may remain unprovisioned;
- the read-only local/CI provider resolves exact scoped and versioned references and rejects
  mutation, stale versions, missing references, staging, and production;
- startup attaches typed model state and readiness exposes only a PASS check, counts, and hashes;
- checked-in examples contain no secret and startup performs zero provider-network calls.

## Reproducible results

- `uv run pytest -q tests/models/test_model_runtime_config.py`: 19 passed;
- affected runtime, registry, security, and baseline selection: 63 passed;
- `uv run pytest`: 272 passed;
- `uv run ruff check src tools tests`: passed;
- `uv run ruff format --check src tools tests`: 85 files formatted;
- `uv run mypy`: 85 source files passed strict checks;
- `uv run python tools/check_controlled_docs.py`: `DOC=PASS version=1.31`;
- all four controlled generators reran with zero working-diff drift;
- `PYTHONUTF8=1 uv run pip-audit --local --progress-spinner off`: passed;
- the 87-component SBOM and license evidence now classify PyYAML 6.0.3 as runtime-direct and bind
  exact SBOM and lock hashes.

## Remaining blockers

This result does not authorize or implement a physical model request. S5-01 unified execution,
S5-06 canonical inspection data, DeepSeek processing/retention/training/commercial review, a live
synthetic provider smoke, a production managed secret adapter, and production approval remain
required. No API credential was requested, stored, logged, committed, or transmitted.
