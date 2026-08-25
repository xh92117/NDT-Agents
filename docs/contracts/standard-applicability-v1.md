# Standard Applicability V1

**Contract version:** 1.0.0

**Task:** S3-08

**Required tests:** EVAL-RETRIEVAL, SEC-TENANT, INT-KNOWLEDGE, QUICK, DOC

## 1. Immutable standard version

A standard version contains exact `TenantScope`, standard type and identifier, edition, title,
publication and effective dates, optional expiry, one canonical region set, lifecycle, rights
basis and evidence reference, required roles, and explicit replacement version IDs. Its ID is the
SHA-256 of the complete versioned payload. Payload tampering invalidates the ID. Registration is
idempotent only for an equal immutable payload.

Publication must not follow the effective date, and expiry must not precede it. Regions, roles,
and replacement IDs are sorted and unique. `GLOBAL` cannot be combined with another region.
Public-domain, licensed, and owner-authorized assertions require a bounded evidence reference.

## 2. Catalog lineage

The catalog key includes tenant, project, user, role tuple, permission version, and standard version
ID. A replacement target must already exist in the same exact scope and share the same standard
type and identifier. Self replacement and any replacement cycle are rejected. Current or
restricted registered versions supersede every version they explicitly replace. No catalog action
publishes an index or approves rights.

## 3. Applicability

One typed request supplies an as-of date, region, and optional canonical standard-type filter. The
deterministic evaluator checks exact scope, current or restricted lifecycle, effective and expiry
dates, exact region or `GLOBAL`, requested type, accepted rights, rights evidence, all required
roles, and supersession. It returns stable denial reason codes rather than assuming missing facts.

Draft, replaced, withdrawn, future-effective, expired, wrong-region, wrong-type, unknown-rights,
expired-rights, prohibited-rights, role-denied, cross-scope, and superseded versions are not
applicable. Restricted versions require both accepted rights and every declared role.

## 4. Retrieval admission

Every governed index snapshot must carry `standard_version_id`. The standard retrieval service
lists only the caller's exact-scope snapshots, resolves that binding in the same-scope catalog,
evaluates applicability, and requires the index snapshot itself to be `PUBLISHED`. Only admitted
snapshots are copied into a transient repository passed to S3-07 hybrid retrieval. Missing or
unregistered bindings and non-published indexes receive explicit denial reasons and never reach
BM25, vector, fusion, or rerank scoring.

The policy is deterministic and makes no LLM, model, network, approval, publication, or retry call.
Licensed production standards and accountable rights approval remain TG-03 external requirements.
