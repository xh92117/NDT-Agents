# Prompt Registry V1

**Task:** S1-18 optimized prompt publication and configured runtime binding

**Contract version:** 1.0.0

## 1. Purpose

The Prompt Registry keeps application-owned system prompts separate from model bindings, secrets,
agent role configuration, runtime graph state, and user data. DeerFlow's configurable custom-agent
`system_prompt` informed the operator-facing shape, while this repository adds exact file hashes,
strict path controls, immutable identities, and recovery invalidation.

## 2. Catalog

`prompts/professional/catalog.v1.yaml` is the only checked-in S1-18 catalog. Every entry contains:

- one stable prompt ID;
- one semantic version;
- one unique relative Markdown path within the catalog directory;
- one exact SHA-256 hash of the UTF-8 file bytes.

The catalog publishes `general`, `technical_qa`, `inspection_plan`, `inspection_report`,
`data_processing`, `method_compatibility`, `knowledge`, and `review`. Agent profiles reference the
first seven through their `prompt` alias. The independent Review Agent resolves `review` through
configured review bindings.

## 3. Loading and validation

The loader accepts one explicit local YAML catalog path. It rejects a non-YAML catalog, BOM,
invalid UTF-8, excessive bytes, YAML aliases or anchors, duplicate keys, unknown fields, duplicate
IDs, versions, or paths, absolute paths, traversal, Windows drive syntax, missing files, symbolic
links, files outside the catalog directory, empty or oversized prompt text, invalid encoding, and
hash mismatch.

Successful loading creates one immutable `ApplicationInstruction` per prompt. The instruction
binds its ID, version, exact text, application origin, and SHA-256. The catalog hash covers the
manifest and resolved identities. The configured agent hash includes that catalog hash, so a prompt
change invalidates stale child and recovery bindings even when the agent YAML is unchanged.

## 4. Execution binding

`ConfiguredExecutorFactory` resolves the profile's instruction before constructing its LangGraph
adapter. The adapter verifies prompt ID, version, and hash, retains the instruction outside graph
state, and passes it to the application-owned child delegate on the single Act call. The stable
`ChildExecutor` boundary still receives only `ChildTaskContext` and returns strict `AgentResult`.

Configured review bindings similarly wrap the reviewer with the exact `review` instruction and
each professional corrector with the responsible child's instruction. A missing prompt or reviewer
version mismatch stops before review or correction execution.

## 5. Prompt requirements

Every role prompt declares its isolated role, minimal-context boundary, untrusted-input handling,
permitted evidence and tools, missing or conflicting input behavior, strict output contract,
uncertainty and limitation handling, human boundary where applicable, no direct user delivery, and
forbidden actions. Professional prompts preserve independent review. The Knowledge Agent cannot
publish directly, and the Review Agent remains independent and read-only.

## 6. Data and security boundary

Raw prompt text is application instruction data. It is not copied into `ChildTaskContext`, persisted
LangGraph input state, audit payloads, secret configuration, or API responses. Only prompt identity,
version, content hash, prompt-catalog hash, and agent-configuration hash cross those boundaries.
Prompt files contain no credential, tenant data, customer content, or provider secret.

S1-18 binds prompt text to injected delegates but does not implement or authorize a live HTTP model
provider. A provider delegate may pass the same verified `ApplicationInstruction` into the existing
`ModelInferenceGateway` only after its model binding, secret, network permission, budget, and data
policy are separately approved.
