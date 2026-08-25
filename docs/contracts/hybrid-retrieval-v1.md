# Hybrid Knowledge Retrieval V1

**Contract version:** 1.0.0

**Task:** S3-07

**Required tests:** EVAL-RETRIEVAL, SEC-TENANT, INT-KNOWLEDGE, SEC-CACHE, QUICK, DOC

## 1. Index candidate

The indexer accepts one S3-06 canonical document only when its complete `TenantScope` equals the
caller scope. It emits an immutable draft snapshot containing corpus, corpus version, index
version, document and source hashes, parser and normalizer versions, access roles, bounded
metadata, and every canonical chunk. Every record retains exact text, page, section, locator,
artifact, version, content hash, tokens, and one fixed-dimension vector.

The embedding port exposes an explicit version and dimension. The built-in deterministic hash
adapter is an offline test and development adapter, not an approved production semantic model.
Changing an embedding model, dimension, tokenizer, chunk, scope, policy, corpus, index, parser,
normalizer, metadata, or role requirement changes or invalidates the snapshot identity.

## 2. Authorization and version filtering

Retrieval first selects snapshots by exact tenant, project, user, complete role tuple, and
permission version. It then permits only `PUBLISHED` snapshots matching the requested corpus,
corpus version, index version, embedding version and dimension, required roles, and exact metadata
filters. Scoring never receives a draft, superseded, withdrawn, stale, cross-scope, role-denied, or
metadata-denied record. Repository keys include all scope fields to prevent cross-owner overwrite.

## 3. Bounded hybrid ranking

The deterministic tokenizer covers case-folded Latin terms, decimal numbers, and Han unigrams and
bigrams. Retrieval combines BM25 full-text rank and cosine vector rank with reciprocal-rank fusion,
then applies a bounded deterministic token-overlap and exact-phrase rerank. Stable chunk and
snapshot identities break ties. The request permits no more than 100 candidates and ten returned
hits; the default top-k is six. There are no retries, network calls, model calls, or side effects.

## 4. Results and citations

Every hit returns exact chunk text, a stable score and component ranks, plus a citation containing
artifact ID and version, source title, media type and hash, parser and normalizer versions, document
ID and hash, chunk and content hashes, page, section path, and locator. This payload is sufficient
to reconstruct and re-attest the source chain without relying on display text.

The frozen synthetic task set must report Recall@6 at least 0.92, nDCG@10 at least 0.85, citation
correctness at least 0.95, and traceability exactly 1.0. Licensed standards, an approved production
embedding, live pgvector/full-text infrastructure, and immutable CI remain TG-03 requirements.
