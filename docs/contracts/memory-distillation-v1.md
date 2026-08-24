# Memory Distillation V1

**Contract version:** 1.0.0  
**Task:** S2-05  
**Status:** isolated provider-neutral implementation

The pipeline starts on context pressure of at least 60 percent, 20 conversation turns, task
completion, explicit user memory intent, or archival. It keeps the six most recent turns and every
protected event raw, and sends only older eligible raw events to one bounded adapter. The adapter
must attest to the exact ordered sources and return a digest of at most 800 tokens.

Fact, inference, and preference proposals remain distinct. User and project candidates preserve
scope, provenance, confidence, classification, expiry, sensitivity, durability, and complete
provider/model/prompt policy versions. Every proposal is stored as `CANDIDATE`; sensitive or
durable candidates are protected and still require approval.

Canonical content hashes remove exact duplicates before persistence. Stable UUIDs derive from
scope, namespace, and content. A different value for an existing fact key creates a conflict that
references both immutable records; neither value is overwritten. One run may propose no more than
30 project facts.
