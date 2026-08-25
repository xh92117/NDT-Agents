# Knowledge Intake V1

**Contract version:** 1.0.0

**Task:** S3-03

**Required tests:** INT-BASH, SEC-BASH, INT-KNOWLEDGE, SEC-TENANT, QUICK, DOC

## 1. Boundary

`ndt_agents.knowledge.intake` accepts only immutable `ArtifactRef` sources bound to the exact
request tenant, project, user, roles, and permission version. It reads the exact literal relative
path through the application-owned `ControlledFileGateway` source adapter. That adapter reuses the
S3-02 traversal, root, symlink, character, scope, and size policy and is not published as a
model-callable raw-byte tool.

The source adapter reads in one-megabyte chunks, checks the hard byte limit during the read,
computes SHA-256 incrementally, and rejects a file that changes size or modification time during
inspection. The intake service compares the observed size and digest to the immutable artifact
record. Original bytes are never edited or replaced.

## 2. MIME and container inspection

Detection uses bounded binary signatures before a filename suffix. V1 accepts PDF, PNG, JPEG,
TIFF, BMP, modern DOCX/XLSX/PPTX, optional legacy DOC/XLS/PPT compound files, Markdown, and plain
text. A suffix may distinguish Markdown from generic text or the three legacy Office compound
types only after the signature class is known. Declared and detected MIME values are recorded
separately; a mismatch requires manual review.

Office Open XML is inspected without extraction. Entry count, entry path, compressed bytes,
expanded bytes, maximum compression ratio, control characters, traversal, drive syntax, and
executable suffixes are checked before the package is eligible for parsing. Unsupported archives,
executable files, unsafe entries, excessive expansion, and invalid packages are rejected.

## 3. Encoding and normalization

Text detection checks UTF-8, UTF-16, and UTF-8 BOMs first, then strict UTF-8, then bounded UTF-16
null-pattern and GB18030/GBK candidates. A user may select UTF-8, GB18030, GBK, UTF-16LE, or
UTF-16BE explicitly. Every decode is strict; replacement decoding is forbidden. Automatic legacy
decisions below confidence 0.80 require manual confirmation.

Accepted text is represented as Unicode and hashed again after UTF-8-without-BOM encoding. The
record retains original and normalized hashes, source encoding, confidence, detection method,
whether a BOM was removed, and `lossy=false`.

## 4. Limits and outcomes

One file is limited to 500 MB, one batch to 50 unique artifacts and paths, and one batch to 2 GB.
Identical accepted content in a batch produces an explicit duplicate result. Outcomes are
`ACCEPTED`, `MANUAL_REVIEW`, or `REJECTED`, with stable codes and next actions for every non-pass
state. Intake does not parse, extract, OCR, index, review, approve, or publish a source.
