# Cache Keys V1

**Contract version:** 1.0.0  
**Task:** S2-08  
**Status:** isolated provider-neutral implementation

Canonical cache keys bind exact tenant, project, user, sorted roles, permission version, RBAC
policy, cache class, normalized request, task type, parameters, model, prompts, Skills, graph,
route policy, tool and adapter, knowledge corpus and documents, public schema, parser, context
policy, and bounded class-specific dimensions.

Unicode input uses NFKC normalization and whitespace collapse; forbidden control characters fail.
Mapping and role order do not affect the key. Any correctness, source, or authorization version
change produces a distinct SHA-256. A separate authorization digest supports audit without
exposing request content.

The cache backend also keys exact tenant, project, user, permission version, and class, so even a
malicious reuse of another scope's external digest misses. Lookup compares the complete current
version manifest, providing revocation and invalidation defense in addition to key separation.
