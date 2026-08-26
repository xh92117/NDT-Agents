# Web Search Tool Contract V1

**Contract version:** 1.0.0
**Task:** S5-03
**Status:** active local implementation

## Purpose

This contract defines a provider-neutral read-only Web Search adapter executed only through the
shared Tool Registry. It retrieves bounded candidate evidence with exact citations. It does not
authorize a live provider or publish knowledge.

## Source policy and network boundary

An application-owned policy maps an exact HTTPS domain or explicitly allowed subdomains to one of
four source classes: government, standards body, vendor, or primary research. Requests may narrow
that policy but cannot add a domain. URL user information, literal IP addresses, localhost, unsafe
schemes, non-default ports, fragments, off-policy redirects, and duplicate URLs fail closed. DNS and
egress enforcement remain mandatory production-adapter controls.

## Budgets

The active defaults permit two unique normalized queries and four opened pages per invocation. The
active limits may be lowered or raised deterministically but never exceed hard limits of four queries
and eight pages. Counts for requested queries, executed provider queries, candidate URLs, opened
pages, and the enclosing physical tool call remain separate. The adapter performs no hidden retry.

## Evidence and citations

Every accepted page becomes one candidate evidence item with exact canonical URL, title, derived
source class, publication and UTC access times, a bounded body locator, content hash, excerpt hash,
provider name and version, `UNTRUSTED` trust label, candidate publication state, and an
instruction-like-text flag. Every item has one stable citation that repeats the source identity and
locator. Missing, rejected, stale, or malformed pages cannot produce a citation.

Page text remains data. Instruction-like text is detected and preserved as an untrusted signal but
is never executed, promoted to instructions, used to expand domains, or granted tool authority.

## Cache

Only non-current successful retrieval snapshots use the S2 retrieval cache. The cache key binds the
exact tenant/project/user/role/permission scope, normalized queries, narrowed domains, source-policy
version, provider version, schema version, and result-affecting limits. A current-information request
always bypasses and does not populate the cache. Cache records contain no secrets, authorization
decisions, side effects, or published knowledge.

## Typed failure

Stable errors distinguish query/page budget, source policy, unsafe URL, current-evidence freshness,
provider offline, provider failure, and malformed response conditions. Failures contain zero
fabricated evidence and citations. Registry permission, secret-purpose, network, data-destination,
timeout, retry, physical-tool budget, output-schema, result-hash, and audit controls remain
authoritative.

The S5-03 tests use an injected deterministic provider and make zero live network calls.
