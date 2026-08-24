# Context Assembly V1

**Contract version:** 1.0.0  
**Task:** S2-01  
**Status:** isolated provider-neutral implementation

## Purpose and boundary

`TaskContextAssembler` creates the frozen V1 `TaskContext` consumed by the existing orchestration
runtime. It does not retrieve data, infer permissions, compress content, read memory, or execute a
tool. Upstream deterministic policy supplies explicit candidates, relevance scores, grants,
clearance, and versioned limits. The assembler validates and reduces that input without an LLM or
network call.

The complete authorization decision report remains with the Main Agent or audit boundary. A child
receives selected content only. Rejected content, access requirements, granted-permission names,
and rejection details do not enter the child context.

The active policy also bounds total candidate JSON bytes before selection. Large bodies must move
to authorized artifacts, so an irrelevant or rejected candidate cannot create an unbounded input.

## Candidate contract

Every context item binds:

- exact tenant, project, user owner, visibility, and permission version;
- required roles and required permissions;
- source type, source reference, source version, source hash, and observation time;
- trust level and data classification;
- canonical JSON content and its verified SHA-256;
- deterministic relevance score and protected status.

Artifact candidates use the same scope, visibility, role, permission, relevance, classification,
and protected checks. Tool authorizations are exact-name, exact-scope, versioned permission
records. An unregistered tool is denied by default.

## Deterministic assembly

The assembler applies this order:

```text
exact tenant and project
  -> user visibility and permission-version freshness
  -> required roles and permissions
  -> classification clearance
  -> protected-aware relevance threshold
  -> canonical content-hash deduplication
  -> protected-first deterministic size and count selection
  -> immutable TaskContext and manifest
```

Deduplication merges only already-authorized candidates. It preserves every selected source label
and the highest selected classification and relevance. Protected content bypasses relevance
dropping. If protected content or protected artifact references exceed the active policy, assembly
fails with a typed next action instead of silently discarding them.

The selected bundle records only authorized entries, their labels, the policy version, selected
content-byte estimate, and a SHA-256 digest of the authorization scope. The final
`context_manifest_sha256` binds the complete `TaskContext` except the self-referential manifest
field. Identical authorized semantic input produces the same ordered output and manifest.

## Child handoff

`ChildContextFactory` accepts a selected bundle only when the parent manifest verifies and the
bundle passes strict validation. The General child receives all selected parent entries.
Professional `ChildInput` values name exact selected content hashes and receive only those entries.
Unknown hashes fail before child creation. Raw parent `dependency_data` still never enters a child.

Legacy S1 task contexts without a selected bundle remain valid and produce an empty child entry
set. This compatibility path does not bypass validation for any S2 bundle.

## Typed failures

Stable failures include budget/task-class mismatch, content-integrity mismatch, protected item or
artifact overflow, parent-manifest failure, invalid selected-bundle schema, and a child request for
an unselected context hash. Each failure states the deterministic repair action and exposes no
candidate content.

## Verification and remaining work

`tests/context/test_context_assembly.py` covers deterministic ordering, provenance-preserving
deduplication, tenant/project/user isolation, stale permissions, roles, permissions,
classification, relevance, artifact and tool denial, C0 losslessness, protected overflow,
authorization-bound manifests, General handoff, professional selection, and tamper rejection.

S2-02 completed the separate C1 through C3 candidate-compression contract. S2-03 still owns
field-level protected-field validation and compression fallback. This contract does not claim
TG-02 or production approval.
