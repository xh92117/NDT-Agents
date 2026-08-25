# Canonical Knowledge Document V1

**Contract version:** 1.0.0

**Task:** S3-06

**Required tests:** INT-MINERU, INT-OCR, normalization regression, INT-KNOWLEDGE, SEC-TENANT, QUICK, DOC

## 1. Input and coverage

The normalizer accepts only an S3-05 `READY` result whose final quality decision is `PASS` and whose
scope matches the caller. Parsed block orders must be unique and contiguous. Every source block is
mapped exactly once; validation fails if any block is lost, duplicated, or reordered ambiguously.
Normalization is deterministic and makes zero external, model, parser, OCR, retrieval, approval,
or publication calls.

## 2. Canonical elements

Element kinds are heading, clause, paragraph, table, formula, figure, list, code, and auxiliary.
Every element carries a stable ID, sequence, page, 0-1000 bounding box, section path, locator type
and value, source block order, exact content, and content SHA-256. Numeric clause identifiers are
recognized deterministically. Heading levels maintain a bounded section hierarchy.

Tables retain both their exact body and rectangular canonical cells. Markdown tables and bounded
simple HTML `table/tr/th/td` markup are parsed as data; markup is never executed. Formulas retain
their exact text. Figures require the already validated relative asset path. Header, footer, page
number, footnote, and aside content remain auxiliary elements instead of being silently discarded.

## 3. Metadata, IDs, and chunks

Metadata has at most 64 lowercase bounded keys and bounded non-control text values, sorted before
hashing. Standard applicability fields are still ordinary untrusted metadata at this task boundary;
S3-08 owns their typed policy.

Document, element, and chunk identities include the relevant exact scope, artifact version, source
hash, parser, normalizer, locator, metadata, and content dimensions. Identical input reproduces the
same result; any correctness dimension changes the document hash.

Each canonical element produces one or more chunks of at most 1,200 characters. Long content is
split by exact character slices so concatenating the parts recovers every character, number, unit,
and punctuation mark. Each chunk retains one element ID, page, section path, locator, part index,
part count, text, and SHA-256. Tables, formulas, figures, and their structured element payloads are
never discarded even when their searchable text spans multiple chunks.
