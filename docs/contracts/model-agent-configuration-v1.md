# Model and Agent Configuration V1

**Task:** S1-17 common hosted-model and planned child-profile configuration

**Contract version:** 1.0.0

## 1. Files

- `config/model-providers/deepseek-v4.v1.json` and
  `config/model-providers/mainstream-llm.v1.json` contain non-secret provider and model metadata.
- `config/runtime/model-bindings.example.yaml` contains all local provider bindings.
- `config/runtime/agent-runtime.example.yaml` contains model aliases and planned child profiles.
- `prompts/professional/catalog.v1.yaml` contains exact prompt identities, versions, relative paths,
  and content hashes; the referenced Markdown files contain the actual system prompts.
- `.env.example` contains blank secret slots and local runtime path examples.
- Local working copies are `.env`, `config/runtime/model-bindings.local.yaml`, and
  `config/runtime/agent-runtime.local.yaml`. They are ignored by Git.

Configuration loading is offline. It validates references, scope, limits, secret selectors, prompt
content, and catalog hashes but performs no provider request.

## 2. Hosted providers

The candidate configuration includes OpenAI, Anthropic, Google Gemini, DeepSeek, Alibaba Model
Studio, Moonshot Kimi, Zhipu BigModel, MiniMax, Baidu Qianfan, Tencent Hunyuan, and Volcengine
Doubao. Provider metadata is based on credential-free official documentation URLs stored in the
catalog. Every provider remains `production_eligible: false`, and every checked-in example binding
remains `state: DISABLED` until the operator supplies its exact environment secret and explicitly
selects it. An ignored local binding may be enabled independently without changing the checked-in
example.

The local secret variables are:

| Provider | Binding | Secret variable | Agent model alias |
|---|---|---|---|
| DeepSeek | `personal-deepseek` | `DEEPSEEK_API_KEY` | `primary` |
| OpenAI | `personal-openai` | `OPENAI_API_KEY` | `openai` |
| Anthropic | `personal-anthropic` | `ANTHROPIC_API_KEY` | `anthropic` |
| Google Gemini | `personal-google` | `GEMINI_API_KEY` | `gemini` |
| Alibaba Model Studio | `personal-alibaba` | `DASHSCOPE_API_KEY` | `qwen` |
| Moonshot Kimi | `personal-moonshot` | `MOONSHOT_API_KEY` | `kimi` |
| Zhipu BigModel | `personal-zhipu` | `ZHIPU_API_KEY` | `glm` |
| MiniMax | `personal-minimax` | `MINIMAX_API_KEY` | `minimax` |
| Baidu Qianfan | `personal-baidu` | `QIANFAN_API_KEY` | `ernie` |
| Tencent Hunyuan | `personal-tencent` | `HUNYUAN_API_KEY` | `hunyuan` |
| Volcengine Doubao | `personal-doubao` | `ARK_API_KEY` | `doubao` |

Only selected bindings should be changed to `ENABLED`. An enabled binding without its secret fails
startup. Filling a secret does not enable its binding automatically.

## 3. Planned child profiles

The checked-in example registers these dispatchable child profiles:

- `general` as the only General Agent;
- `technical_qa`;
- `inspection_plan`;
- `inspection_report`;
- `data_processing`;
- `method_compatibility`;
- `knowledge`.

Professional profiles use the existing review-required path. The independent Review Agent is not
a dispatchable child profile. It remains an injected `ReviewExecutor`, and correction executors
remain bound to the responsible professional child type. This prevents a normal route from using
the reviewer as a child worker.

All example profiles use the `primary` model alias. To use another configured provider for one
profile, change only its `model` field to one of the aliases in the table and enable the matching
binding after provisioning the matching secret.

Each profile's `prompt` field is an alias into the strict prompt catalog. It is not inline prompt
text or a filesystem path. The catalog resolves the exact application instruction before execution,
and its hash contributes to the immutable agent-configuration hash.

## 4. Local setup

1. Copy `.env.example` to `.env`.
2. Copy both runtime `*.example.yaml` files to the matching `*.local.yaml` filenames.
3. Put secrets only in `.env`.
4. Change only the selected provider bindings from `DISABLED` to `ENABLED`.
5. Export `NDT_MODEL_CONFIG`, `NDT_PROMPT_CONFIG`, `NDT_AGENT_CONFIG`, and
   `NDT_MODEL_ENV_FILE=.env` in the process or IDE before startup. The application deliberately does
   not auto-discover dotenv files.

The application-owned General model delegate remains off unless both of these process settings are
present:

- `NDT_GENERAL_MODEL_DELEGATE_ENABLED=true`;
- `NDT_DEEPSEEK_POLICY_ACKNOWLEDGEMENT=I_ACKNOWLEDGE_UNVERIFIED_DEEPSEEK_PROVIDER_POLICY`.

This switch is accepted only in the `local` environment and still requires the exact enabled
DeepSeek binding, secret, prompt catalog, and agent catalog. It permits only authenticated G0 Web
tasks over same-scope deterministic SIMULATED fixture data. It does not permit customer data,
professional execution, formal use, publication, retry, fallback, tools, or production deployment.
The active total-token limit is 6000 for the 3400-input plus 2048-output reservation; the hard G0
limit remains 8000.

## 5. MinerU

The active parser boundary is still `MinerUCliRunner`, which runs the pinned local MinerU command
and validates Markdown, content-list JSON, and middle JSON. For mainland China, the local example
uses `MINERU_MODEL_SOURCE=modelscope`; `huggingface` and `local` are other MinerU-supported values.

`MINERU_API_BASE_URL` and `MINERU_API_TOKEN` in `.env.example` are reserved values. They are not an
active API adapter and are not read by the current parser. The official hosted service currently
documents token-authenticated precision extraction at `https://mineru.net` and token-free,
rate-limited lightweight agent extraction. Activating hosted parsing requires a separate typed
adapter, Tool Registry entry, timeout and polling policy, output validation, audit, tests, and an
explicit network permission. A token value alone must not silently replace the local CLI path.

## 6. Safety boundary

These files are local candidate configuration, not a provider approval or production selection.
They allow only PUBLIC and SYNTHETIC data, retain unverified provider policy metadata, contain no
secret value, and do not close S0-05, TG-00, TG-01, TG-03, or TG-05.
