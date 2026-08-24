# Runtime API V1

**Contract version:** 1.0.0  
**Task:** S1-01  
**Status:** isolated local candidate; not approved for production deployment

## Application factory

`ndt_agents.runtime.app.create_app` builds the FastAPI application without contacting a database,
cache, object store, model provider, or external network. It may perform bounded local reads of an
explicit model YAML, catalog JSON, and local/CI environment file. The factory accepts an immutable
`AppSettings` value. When no value is supplied, it reads only the supported `NDT_` environment
keys. Unknown keys, invalid values, and unsafe production settings fail with a stable
`ConfigurationError.code` and do not echo the rejected value.

## Configuration

| Environment key | Field | Default | Constraint |
|---|---|---|---|
| `NDT_SERVICE_NAME` | service name | `ndt-agents` | 1 to 64 characters |
| `NDT_ENVIRONMENT` | environment | `local` | `local`, `ci`, `staging`, or `production` |
| `NDT_LOG_LEVEL` | log level | `INFO` | standard uppercase Python levels |
| `NDT_HOST` | bind host | `127.0.0.1` | 1 to 255 characters |
| `NDT_PORT` | bind port | `8000` | 1 to 65535 |
| `NDT_EXPOSE_API_DOCS` | API docs | `false` | forbidden in production |
| `NDT_MODEL_CONFIG` | model YAML path | unset | explicit UTF-8 YAML path |
| `NDT_MODEL_ENV_FILE` | local secret file path | unset | requires model config; forbidden in production |

The package version is the service version and cannot be overridden by an environment value.
Model configuration is opt-in: when unset, startup behavior remains provider-neutral. When set,
the application attaches the typed result to `app.state.model_runtime`; it never places secret
values in settings, health output, logs, or serialized status.

## Health resources

`GET /health/live` returns HTTP 200 after the process can serve an ASGI request. Its check name is
`process`.

`GET /health/ready` returns HTTP 200 after the application scaffold initializes. Its check name is
`application`. A successfully selected model bootstrap adds a non-secret `model_configuration`
PASS check. Invalid configuration fails startup instead of publishing a false-ready application.
Injected dependency probes extend readiness without making liveness depend on an external service.
A failed dependency makes readiness return HTTP 503, overall `FAIL`, and the typed probe error code.

Both resources return a strict `HealthResponse`:

```json
{
  "schema_version": "1.0.0",
  "service": "ndt-agents",
  "service_version": "0.1.0",
  "status": "PASS",
  "checks": [
    {
      "name": "process",
      "status": "PASS",
      "error_code": null
    }
  ]
}
```

## Correlation, logging, and failures

The service accepts a bounded safe `X-Request-ID` or generates a 32-character opaque identifier.
It returns the identifier on every response. Logs are one JSON object per event and include UTC
time, severity, logger, service, environment, event fields, and request correlation when present.
Common inline credential forms are redacted. Arbitrary `LogRecord` fields are not serialized.

Unhandled failures return HTTP 500 and the strict `ProblemDetail` schema. The response contains a
stable `error_code`, safe message, request ID, retryability, and required next action. It never
contains the exception message or stack. HTTP and request-validation failures are also mapped to
the same versioned schema.

Every response sets `Cache-Control: no-store` and `X-Content-Type-Options: nosniff`. API docs and
OpenAPI are disabled by default.

## Deferred boundaries

Storage readiness, OIDC, tenant/project authorization, rate limits, TLS, encryption, audit storage,
and approval controls belong to S1-02 through S1-13. This scaffold does not claim those controls.
