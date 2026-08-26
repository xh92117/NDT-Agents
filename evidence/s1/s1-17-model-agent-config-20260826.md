# S1-17 Model and Agent Configuration Evidence

Status: PASS for the local mutable S1-17 task profile

## Candidate and environment

- Branch: `codex/langgraph-child-runtime`
- Base commit: `966624f7b340`
- Operating system: local Windows
- Python: CPython 3.12.13
- uv: 0.11.20
- Network behavior: configuration load and tests made no provider or MinerU network call
- Secret behavior: checked-in examples contain blank variable slots only; ignored local files are
  created with blank values and are not test evidence for a provisioned provider

## Implemented configuration boundary

- Two application-owned catalogs publish eleven candidate hosted text providers: DeepSeek, OpenAI,
  Anthropic, Google Gemini, Alibaba Model Studio, Moonshot Kimi, Zhipu GLM, MiniMax, Baidu Qianfan,
  Tencent Hunyuan, and Volcano Engine Doubao.
- Each local binding is independently selectable, `DISABLED` by default, non-production eligible,
  and restricted to PUBLIC or SYNTHETIC data. No binding grants network use.
- Each binding references one environment variable and one exact secret purpose. No key value is
  stored in YAML or JSON. Anthropic's `x-api-key` scheme and bearer schemes remain explicit on the
  resolved model route for a future provider adapter.
- Exact case-sensitive provider model identifiers, including `MiniMax-M2.7`, validate without
  normalization.
- The DeerFlow-shaped agent document publishes eleven model aliases and seven dispatchable child
  profiles: `general`, `technical_qa`, `inspection_plan`, `inspection_report`, `data_processing`,
  `method_compatibility`, and `knowledge`.
- There is exactly one General Agent. The other six are professional children with bounded turns
  and timeouts and no unregistered tools. The Review Agent remains the separately injected S1-16
  reviewer and is not a user-dispatchable child profile.
- Existing exact-catalog runtime checks remain fail closed: startup requires one executor for every
  configured child and one corrector for every professional child.

## MinerU boundary

- The active knowledge parser remains the pinned local `mineru` CLI adapter.
- `MINERU_MODEL_SOURCE` selects the local model source and defaults to `modelscope`.
- `MINERU_API_BASE_URL` and `MINERU_API_TOKEN` are reserved placeholders only. They do not activate
  the hosted MinerU API because no hosted MinerU Tool Registry adapter exists in this task.
- A future hosted adapter must register exact endpoints, token purpose, permissions, timeout,
  budgets, audit, asynchronous result handling, and output validation before those values are used.

## Reproducible verification

Offline local-load proof:

```text
$env:PYTHONPATH='src;.'
uv run python -c "from ndt_agents.models.config import load_model_runtime_configuration; from ndt_agents.orchestration.agent_config import load_agent_runtime_configuration; m=load_model_runtime_configuration('config/runtime/model-bindings.local.yaml', env_file_path='.env'); a=load_agent_runtime_configuration('config/runtime/agent-runtime.local.yaml', model_runtime=m); print({'catalogs':m.status.catalogs,'bindings':m.status.bindings,'enabled_bindings':m.status.enabled_bindings,'provisioned_secrets':m.status.provisioned_secrets,'models':a.status.models,'agents':a.status.agents,'profiles':[p.name for p in a.profiles]})"
```

Result: two catalogs, eleven bindings, zero enabled bindings, zero provisioned secrets, eleven model
aliases, and seven exact child profiles loaded without a network call.

Task and regression commands:

```text
uv run ruff check src tools tests
uv run ruff format --check src tools tests
uv run mypy
uv run python tools/check_controlled_docs.py
uv run pytest tests/models tests/orchestration/test_agent_runtime_config.py tests/knowledge/test_mineru.py
uv run pytest
git diff --check
```

Results:

- Ruff passed.
- Format check passed for 197 files.
- Strict mypy passed for 197 source files.
- DOC passed at controlled-document version 1.75.
- The task-focused configuration, model, orchestration, and MinerU suite passed all 105 cases.
- Complete regression collected 1072 cases: 1071 passed with one existing Windows filename skip.
- Diff checks passed; the only output was the existing Git LF-to-CRLF warning for `.env.example`.
- The refreshed code graph contains 3578 nodes, 32509 edges, and 210 tracked files in Python,
  JavaScript, and Rust, with no graph update errors.

## Limits

This task publishes configuration and strict loading contracts, not live model adapters. Every
hosted binding remains disabled and unapproved; setting a key alone does not authorize or perform a
provider call. No managed secret store, approved provider region/retention/training policy, live
token-metered smoke result, production model benchmark, hosted MinerU adapter, immutable CI
candidate, or accountable security/license approval is present. S0-05, TG-01, TG-03, TG-05, and
commercial-release requirements remain unchanged.
