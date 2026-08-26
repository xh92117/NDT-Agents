# Technical QA Skill V1

## Purpose

S4-01 adds a provider-neutral Technical QA boundary. It validates a typed child-agent candidate
against exact-scope S3-07 retrieval evidence. It does not call a model, establish expert truth,
approve a formal conclusion, or replace the S1-09 Review Agent.

## Contracts

`TechnicalQARequest@1.0.0` binds the task and request IDs, question, method, structure and material
applicability inputs, corpus/index/embedding versions, metadata filters, and retrieval limits.
Supported V1 method codes are `UT`, `GPR`, `IE`, `RT`, `AE`, and `MV`. Structure and material codes
come from `domain/ontology.v1.json`.

`TechnicalQACandidate@1.0.0` contains a summary, bounded claims, missing inputs, and an overall
limitation. Every claim records severity, applicability, conclusion level, limitations,
uncertainty, human-confirmation state, and zero or more proposed support bindings. A support binding
contains only a chunk ID, an exact quote, and sorted unique matching terms.

`TechnicalQAResult@1.0.0` binds the exact scope, Skill and prompt versions, request hash, retrieval
query hash, status, validated claims, rebuilt citations, issues, evidence snapshot IDs, human
boundary, and a deterministic result hash. The service creates citations from repository records;
candidate-supplied citation metadata is never trusted.

## Validation order

1. Missing method, structure, or material fields return `NEEDS_USER` before retrieval.
2. Values outside the V1 ontology return `HUMAN_REQUIRED` before retrieval.
3. Retrieval runs through S3-07 for the exact tenant, project, user, roles, and permission version.
4. Every used snapshot is rechecked for exact scope, `PUBLISHED` state, version manifest, metadata,
   embedding, and required roles.
5. Every hit is reconstructed from its immutable index record. Source, artifact, document, chunk,
   parser, normalizer, content hash, page, locator type, locator, and text must match exactly.
6. A support quote must be an exact substring of the retrieved chunk. Every declared matching term
   must occur in the claim, quote, and their deterministic token intersection.
7. A claim without validated evidence is explicit. An unsupported critical claim and every formal
   conclusion require a qualified human. No result silently becomes definitive.

The same input, candidate, repository state, and version manifest produce the same claim IDs,
citations, issues, and result hash. There is no retry, network, model, approval, publication, or
instrument side effect in this boundary.

## Local evidence boundary

Synthetic tests cover exact citation reconstruction, stable hashing, missing inputs, out-of-domain
values, absent candidates, unrelated evidence, stale/non-published/cross-scope evidence, critical
claims, formal conclusions, and strict candidate contracts. Expert pass rate and the full TG-04
threshold remain blocked until R-008 and R-009 close with licensed evidence and adjudicated gold
answers.
