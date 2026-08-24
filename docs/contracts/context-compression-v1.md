# Context Compression V1

**Contract version:** 1.0.0  
**Task:** S2-02  
**Status:** isolated provider-neutral implementation

## Purpose and boundary

`ContextCompressor` selects and executes C0 through C3 from a single versioned policy. It accepts
only an ordered, hash-verified raw-event stream for one exact task and tenant scope. It does not
retrieve events, create checkpoints, validate protected fields inside a semantic summary, or make
a semantic result execution-ready. S2-03 owns that field-level validation and automatic fallback.

The semantic adapter is a narrow asynchronous port. No model, prompt, provider, or network client
is embedded in the compression policy. Adapter results bind provider, model, prompt, exact ordered
source-event IDs, structured content, and an output-token count.

## Raw-event contract

Every event binds an ID, task, exact tenant/project/user/permission scope, monotonic sequence,
event kind, canonical content hash, token estimate, protected flag, creation time, and optional
recoverable immutable artifact. The `is_semantic_summary` discriminator is fixed to false, so a
prior summary cannot be supplied as a raw event.

Requests reject duplicate IDs, duplicate sequences, reordered events, hash mismatch, and any event
or recoverable artifact outside the exact active scope before a semantic call. The raw-event
manifest hash covers the full ordered input.

## Level policy

| Level | Active pressure | Operation | Result state |
|---|---:|---|---|
| C0 | below 40 percent | lossless content-hash deduplication | `READY` |
| C1 | 40 percent to below 60 percent | C0 plus hash-bound artifact references for recoverable non-protected tool logs | `READY` |
| C2 | 60 percent through 80 percent | retain all protected events and six recent conversation turns; summarize other raw events to at most 800 tokens | `REQUIRED` |
| C3 | above 80 percent | require an exact-scope durable checkpoint; retain protected events; build a task digest of at most 1,200 tokens | `REQUIRED` |

Protected events are never replaced by an artifact reference or sent to the semantic adapter.
Exact duplicate non-protected content preserves every source event ID. C1 artifact references bind
the source-event content hash and immutable artifact hash, making the replacement recoverable.

## Semantic safety boundary

C2 and C3 enforce these pre-validation controls:

- at most two semantic compressions per task;
- exact ordered source-event attestation from the adapter;
- level-specific output-token limits;
- rejection when the candidate does not reduce the eligible raw-event token estimate;
- reconstruction from raw events on every call;
- no semantic call when deterministic C0 or C1 is selected;
- a matching task and scope checkpoint before C3.

A C2 or C3 result is always emitted with `validation_state=REQUIRED` and
`execution_ready=false`. It is a candidate, not an authorized child or Main Agent context. S2-03
must validate protected constraints, values, units, identifiers, citations, decisions, conflicts,
errors, hashes, permissions, and approvals, then accept or retry at a less aggressive level.

## Typed failures

Stable actionable failures cover cross-scope raw events, missing semantic adapter, exhausted
semantic-compression count, missing or cross-scope C3 checkpoint, source-event attestation
mismatch, and semantic output overflow. Strict model validation rejects malformed contracts before
the pipeline runs. Adapter exceptions and non-reducing candidates are converted to typed failures
before a result is created.

## Verification and remaining work

`tests/context/test_context_compression.py` covers all threshold boundaries, C0 and C1 zero-call
behavior, lossless provenance, recoverable log references, C2 recent-turn retention, protected
event retention, representative token reduction, C3 checkpoint enforcement, scope isolation,
semantic-call limits, source attestation, output limits, ordered raw input, integrity, and
summary-on-summary rejection.

S2-03 still owns critical-field extraction, candidate comparison, acceptance, rejection, and
automatic fallback. Therefore S2-02 alone does not satisfy final `EVAL-COMPRESSION`, TG-02, or
production approval.
