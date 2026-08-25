# MinerU Adapter V1

**Contract version:** 1.0.0

**Task:** S3-04

**Required tests:** INT-MINERU, INT-KNOWLEDGE, SEC-BASH, SEC-TENANT, QUICK, DOC

## 1. Invocation boundary

The adapter accepts only an S3-03 `ACCEPTED` intake record that matches the exact immutable
`ArtifactRef`, scope, literal relative path, byte count, detected media type, and source SHA-256.
It obtains the source path through the S3-02 application source adapter. Text and Markdown become a
zero-tool typed parse document; legacy Office compound files return an explicit registered
conversion requirement.

MinerU execution is bound to one executable path and SHA-256, parser version, tenant, project,
source root, existing working output root, explicit config file, and timeout no greater than 900
seconds. The command is an argument array containing only `-p`, `-o`, `-m`, `-b pipeline`,
`-l ch`, `-f true`, and `-t true` with application-derived values. It never uses a shell, API URL,
model-provided flag, arbitrary backend, or implicit user configuration.

The current command surface follows the official MinerU CLI documentation reviewed on 2026-08-25:
`mineru` accepts input with `-p`, output with `-o`, method `auto|txt|ocr`, backend selection,
language, formula, and table options. The adapter pins the pipeline backend because structured
formats differ by backend and version.

## 2. Output contract

One run-specific output directory must contain exactly one Markdown file, one legacy
`*_content_list.json`, and one `*_middle.json`. This matches the official MinerU output reference,
which describes Markdown plus the content list for readable blocks and middle JSON for page and
intermediate structure. Optional debug, image, and newer V2 files do not replace the three required
V1 artifacts.

All required files are byte-bounded before context entry. Markdown and JSON must be strict UTF-8;
JSON duplicate keys are rejected. Middle JSON must report the pinned `pipeline` backend and parser
version, unique contiguous zero-based pages, and positive page sizes. Content blocks are bounded,
ordered, tied to a known page, restricted to known types, and carry ordered 0-1000 coordinates.
Asset paths must remain relative to the run output. Exact hashes are recorded for all three files.

## 3. Failures and deferred behavior

Timeout, process failure, output link or path escape, missing or duplicate required files, excessive
output, malformed JSON, unknown block type, invalid coordinates, page mismatch, backend mismatch,
version mismatch, source mismatch, and scope mismatch return typed failures. S3-05 owns quality
classification and fallback; S3-06 owns canonical domain normalization.
