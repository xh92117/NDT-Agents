# Context Validation V1

**Contract version:** 1.0.0  
**Task:** S2-03  
**Status:** isolated provider-neutral implementation

## Boundary

`ContextCompressionValidator` consumes the exact raw compression request and its C0-C3 candidate.
It rejects task, scope, raw-manifest, or source-event coverage mismatch before measuring content.
Semantic output never becomes execution-ready without a hash-bound validation report.

## Retention model

The validator flattens canonical JSON leaves from raw events and output items. An atom is critical
when its event is protected, its field identifies an instruction, security or permission state,
tenant, conflict, unresolved issue, standard, clause, numeric value, unit, citation, source hash,
tool error, approval, or decision, or its value is numeric. Other confirmed leaves are
non-critical facts.

Acceptance requires all of:

- critical retention equal to 100 percent;
- confirmed non-critical retention at least 98 percent;
- supplied answer-quality degradation no more than three percentage points;
- every raw event covered exactly once;
- exact task, scope, policy, and raw-event manifest binding.

Hash-bound immutable artifact references satisfy atoms from the referenced raw tool event because
the C1 contract preserves its source hash. Missing semantic quality evidence is unsafe.

## Fallback

An unsafe C2 candidate is rebuilt from raw events at C1. An unsafe C3 candidate is rebuilt at C2,
then C1 if necessary. The existing two-semantic-compression task limit remains active. Fallback
never accepts a prior summary as raw input and never exceeds the configured level token limit.

A passing result changes to `READY`, carries the validation-report SHA-256, and becomes
execution-ready. Exhaustion preserves the uncompressed raw context and returns a typed action.

## Verification

`tests/context/test_context_validation.py` covers safe semantic acceptance, critical and
non-critical loss, quality evidence and degradation, C2 and C3 fallback, the two-call limit,
raw-event reconstruction, proof binding, task mismatch, and exact source coverage.
