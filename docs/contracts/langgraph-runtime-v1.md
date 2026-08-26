# LangGraph Child Runtime and Agent Configuration V1

## Status and scope

This contract defines the first application-owned LangGraph adapter and the strict local agent
runtime configuration for S1-14. It does not enable a live model provider, production persistence,
background execution, direct child-to-user delivery, or a production deployment.

The configuration shape is informed by DeerFlow's versioned root configuration, named model list,
global subagent defaults, and per-agent overrides. DeerFlow remains a reference rather than a
runtime dependency:

- [DeerFlow configuration guide](https://github.com/bytedance/deer-flow/blob/main/backend/docs/CONFIGURATION.md)
- [DeerFlow example configuration](https://github.com/bytedance/deer-flow/blob/main/config.example.yaml)
- [DeerFlow API guide](https://github.com/bytedance/deer-flow/blob/main/backend/docs/API.md)

## Runtime boundary

The adapter implements the existing `ChildExecutor` port. It accepts only one validated minimal
`ChildTaskContext`, resolves one immutable application-owned agent profile, and compiles a typed
LangGraph state machine with this fixed sequence:

```text
START -> Observe -> Plan -> Act -> Verify -> END
```

Observe validates context and selected profile identity. Plan records the bounded execution plan.
Act invokes the injected prompt-aware child delegate exactly once with the resolved immutable
application instruction. The instruction is held by the adapter and is not added to graph state.
Verify validates the strict `AgentResult`,
task and run identity, and tenant and project artifact scope. The enclosing child subgraph remains
the authority for terminal topology, review requirements, aggregation readiness, graph budgets,
and user-delivery denial.

The adapter performs no retry. It converts known configuration, timeout, and validation failures to
stable typed child errors. A checkpointer may be injected when the application assembles the graph,
but the configuration cannot import one or select a production storage implementation.

## Configuration document

The document has `schema_version`, `config_version`, `models`, and `subagents` at its root. The
separate prompt catalog is selected explicitly by `NDT_PROMPT_CONFIG`.

Each named model entry contains only a display name plus exact references to an existing model
binding and requested model identity. Capability flags and input/output token limits are descriptive
constraints that must not exceed the resolved registry binding. It contains no endpoint, API key,
environment variable name, provider SDK class, or arbitrary Python import path.

The subagent section contains bounded global defaults and a non-empty `agents` list. Every agent
has a stable name and kind, description, model alias, prompt alias, Skill version, graph version,
allowed Tool Registry identities, maximum turns, and timeout. Exactly one General Agent must be
registered. Professional profiles remain isolated and review-required under the existing topology.

The loader accepts one explicit YAML path. It reads bounded UTF-8 without BOM, rejects aliases,
anchors, duplicate mapping keys, unknown fields, duplicate names, invalid semantic versions,
unresolved model or prompt aliases, and unsafe or non-YAML paths, and computes a canonical
configuration hash that includes the prompt-catalog hash.
It performs no environment expansion, dynamic import, filesystem discovery, provider call, or
network call.

## DeerFlow differences required by this repository

DeerFlow permits a model implementation class path and secret interpolation in model entries. This
runtime intentionally replaces those fields with the existing `ModelApiRegistry` binding and model
identities. DeerFlow custom-agent tool names are similarly restricted to the application-owned Tool
Registry snapshot supplied at assembly time. These differences preserve exact versions, tenant and
project authorization, secret isolation, auditability, deterministic startup, and replacement of
LangGraph without changing public contracts.

## Versioning and operations

The LangGraph package is an exact runtime dependency and must appear in `pyproject.toml`, `uv.lock`,
the CycloneDX inventory, and official release-metadata license evidence. Changes to its version,
graph topology, agent configuration schema, model resolution, or checkpointer behavior trigger the
S1-14 task profile. A configuration change produces a new canonical hash and invalidates any
runtime assembly bound to the prior hash.
