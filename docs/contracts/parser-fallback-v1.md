# Parser Fallback V1

**Contract version:** 1.0.0

**Task:** S3-05

**Required tests:** INT-MINERU, INT-OCR, INT-KNOWLEDGE, SEC-TENANT, BUDGET, QUICK, DOC

## 1. Quality gate

The deterministic quality gate evaluates the same typed `ParsedDocument` after every parser stage.
It measures expected page coverage, meaningful alphanumeric characters per non-drawing page,
Unicode replacement-character ratio, expected table coverage, and expected formula coverage.
Defaults are page coverage 0.95, at least 50 meaningful characters, corrupted characters no more
than 0.01, and expected table/formula coverage 0.95. Page expectations and drawing classifications
are versioned input; low-text drawings do not fail text density.

Every page retains its presence, drawing classification, character counts, corrupted ratio,
table/formula flags, and reason codes. Whole-document reasons and failed page indexes are also
preserved.

## 2. Bounded fallback

The sequence is fixed:

```text
MinerU txt once -> MinerU OCR once -> independent OCR once -> manual review
```

No stage repeats. Exact scope is checked before the first call, and every adapter re-attests the
same immutable source path, size, and SHA-256. Each parsed attempt records the parser, version,
method, canonical document hash, and quality decision; each failed attempt records a stable error
code. Total physical parser calls cannot exceed three.

When selected pages fail, the next validated document replaces only those pages. Earlier good pages
are retained. A merge requires identical tenant, project, user, artifact, MIME, and source hash and
records hashes of both inputs plus the replaced page list. The merged result passes through the same
quality gate before it can become ready.

## 3. Independent OCR and explicit failure

The independent OCR adapter is provider-neutral but requires one registered engine name and
version. It reuses the S3-02 source path, returns contiguous zero-based pages with positive size and
bounded non-empty text, and becomes a typed `ParsedDocument` with one physical call. A production
engine binding remains an environment decision and must use the registered tool boundary.

If all three stages fail or remain below quality thresholds, the result is `MANUAL_REVIEW`. It
contains all attempts, the exact call count, a failure code, and the next action and contains no
publishable document.
