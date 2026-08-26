# DeepSeek Provider Adapter V1

**Task:** S5-07-LIVE first hosted-model transport

**Contract version:** 1.0.0

**Required tests:** UNIT-MODELREG, PROVIDER-SMOKE, SEC-PLATFORM, SEC-TOOLS, BUDGET,
OBS-AUDIT, QUICK, DOC

## 1. Boundary

`DeepSeekModelInferenceProvider` is an opt-in adapter behind the existing S5-07
`ModelInferenceProvider` port. It does not bypass route authorization, model-call and token budgets,
strict output validation, review requirements, or hash-only audit. Application startup can load an
enabled local binding and its ignored environment secret without constructing the adapter or making
a network request.

The adapter accepts only provider `deepseek` version `1.0.0`, endpoint `openai-chat`, protocol
`OPENAI_CHAT_COMPLETIONS`, the exact URL
`https://api.deepseek.com/chat/completions`, one cataloged DeepSeek V4 model ID, and credential
purpose `model.deepseek.credential`. Any mismatch stops before secret resolution and network.

## 2. Request contract

The gateway includes the exact application instruction, canonical inspection manifest, bounded
parameters, registered output schema identity/content/hash, and sorted required quality metrics in
the hash-protected `ModelProviderRequest@1.0.0`. The adapter creates one non-streaming Chat
Completions request with:

- the registered instruction as the system message;
- canonical data, bounded parameters, and the exact response contract as untrusted user data;
- the selected model ID and maximum output-token cap;
- JSON-object response mode, `stream: false`, and deterministic temperature zero;
- no caller-selected URL, header, model control, retry, fallback, tool call, or redirect.

The response contract is an envelope with `output`, `confidence`, and exactly the registered metric
names. The gateway independently validates the inner output against the registered JSON Schema and
checks profile thresholds before any output enters agent context.

## 3. Credential and transport controls

The scoped secret reference is resolved only after the exact route and request contract pass local
validation. The plaintext value exists only long enough to construct the HTTPS `Authorization:
Bearer` header. It is excluded from Pydantic contracts, request bodies, replies, exceptions, logs,
audit, and evidence.

The default stdlib transport uses the operating-system trust store through a default TLS context,
denies redirects, sends one `POST`, applies a bounded timeout, and reads at most 2 MiB. The encoded
request is also limited to 2 MiB. There is no adapter retry. Timeout, DNS/network, TLS, oversized
request/response, and HTTP failures return typed provider errors with a physical-network-call count
of zero or one.

## 4. Response validation

HTTP 200 is not success by itself. The adapter requires duplicate-free bounded UTF-8 JSON, a
bounded provider request ID, the exact model ID, exactly one choice, valid non-negative prompt and
completion token counts, a supported finish reason, and a duplicate-free JSON response envelope.
The envelope must contain only one object output, Decimal confidence in `[0, 1]`, and exactly the
sorted required Decimal metrics.

`stop` produces a provider success candidate. `length` maps to `MODEL_INCOMPLETE`,
`content_filter` maps to `MODEL_REFUSED`, and `insufficient_system_resource` maps to retryable
`MODEL_PROVIDER_UNAVAILABLE`. Other finish reasons fail closed. The gateway still binds the reply
to exact call, request, profile, provider, endpoint, model snapshot, usage, schema, thresholds, and
budget before returning a result.

The documented HTTP mapping is:

| HTTP | Provider error | Retryable |
|---:|---|---|
| 400, 422 | `MODEL_PROVIDER_REQUEST_INVALID` | no |
| 401 | `MODEL_PROVIDER_AUTHENTICATION_FAILED` | no |
| 402 | `MODEL_PROVIDER_BALANCE_EXHAUSTED` | no |
| 429 | `MODEL_RATE_LIMITED` | yes |
| 500, 503 | `MODEL_PROVIDER_UNAVAILABLE` | yes |

Other HTTP failures map to `MODEL_PROVIDER_FAILED`, retryable only for other 5xx responses. Raw
provider error bodies never enter the typed result or model context.

## 5. Local construction and enablement

The ignored local binding `personal-deepseek` may be set to `ENABLED` after `DEEPSEEK_API_KEY` is
present in the explicitly selected ignored `.env`. Offline configuration loading must report one
enabled and one provisioned binding without displaying a value. The adapter is constructed only at
the authorized execution boundary:

```python
from ndt_agents.models.deepseek import build_deepseek_provider

provider = build_deepseek_provider(configured_model_runtime)
```

The resulting provider must be injected into `ModelInferenceGateway`; it is not a direct child-agent
delegate and does not create a second inference path.

## 6. Live-smoke gate

Offline injected-transport tests make zero physical network calls. A live smoke must use fixed
PUBLIC or SYNTHETIC input, one small output cap, no fallback, and the normal gateway. It may run only
after an operator explicitly acknowledges the catalog's still-unverified processing-region,
retention, training-use, and commercial-term states. Without that acknowledgement, preflight stops
before secret resolution and network. A local key and enabled binding do not imply provider-policy
approval or production eligibility.
