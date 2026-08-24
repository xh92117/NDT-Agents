# Cache Service V1

**Contract version:** 1.0.0  
**Task:** S2-07  
**Status:** isolated provider-neutral implementation

One strict service supports exact response, retrieval, pure tool result, parse result, and semantic
cache classes. Entries preserve exact scope, immutable value hash, complete version manifest,
provenance, validation state, saved-token estimate, creation time, and class TTL.

Default TTLs are 24 hours for exact, six hours for retrieval, 30 days for pure tools, 90 days for
parse results, and one hour for semantic results. Expiry or any version mismatch rejects and
removes an entry. Current-information requests always bypass the cache. Metrics keep hits, misses,
stale rejections, bypasses, and saved tokens separate.

Secrets, authorization decisions, unstable values, write side effects, and non-pure tool results
are never cached. Semantic caching is restricted to G0/P1 tasks and similarity at least 0.95.
Different values at one immutable key are treated as poisoning unless an explicit governed refresh
is requested. PostgreSQL storage uses exact user scope and forced RLS.
