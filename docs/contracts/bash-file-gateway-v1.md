# Controlled Bash File Gateway V1

**Task:** S3-02

**Contract version:** 1.0.0

**Required tests:** INT-BASH, SEC-BASH, UNIT-TOOLREG, SEC-TOOLS, BUDGET, OBS-AUDIT, QUICK, DOC

## 1. Boundary

`ndt_agents.tools.file_gateway` provides the local-file capabilities registered through the shared
S1-12 Tool Registry. The word Bash identifies the approved local command family; the runtime never
accepts or constructs a shell program. Read-only operations invoke exact application-owned
executables with argument arrays. Mutations use application-owned safe wrappers.

The V1 tools are `file.list`, `file.search`, `file.read`, `file.write`, `file.edit`,
`file.rollback`, and `file.execute`. They do not expose deletion, general move, permission change,
background launch, package installation, arbitrary executable selection, child shells, or network
access.

## 2. Publication and scope

One `ControlledFileGateway` is bound to an exact resolved tenant/project root. Every definition is
application-owned, network-free, strict-schema, byte- and time-bounded, permission-controlled, and
audited by the shared registry. The caller must present the same tenant and project in its
`ToolInvocationContext`; user and permission versions remain enforced by the Tool Registry.

The gateway discovers or receives exact `ExecutableIdentity` records. Every physical command
recomputes and compares the executable SHA-256 before process start. The default fixed templates
use `find -- path -mindepth 1 -maxdepth 1 -print0`, `grep -n -F -e pattern -- path`, and
`cat -- path`. NUL-delimited listing preserves exact filenames before control-character policy is
applied. The environment fixes `LANG` and `LC_ALL` to `C.UTF-8`, replaces `PATH` with the
executable directory, and captures
bounded stdout and stderr. `shell=True`, `bash -c`, pipelines, redirection, substitution, and
model-provided flags are absent.

`file.execute` accepts only an application-published `ExecutionTemplate`. The model chooses a
stable command ID and bounded authorized paths; it cannot choose an executable or flags.

## 3. Path and mutation policy

User paths are literal relative values. Absolute and drive-relative paths, traversal, control
characters, wildcard syntax, shell metacharacters, internal version storage, and resolved paths
outside the configured root are denied. Spaces, Chinese characters, brackets, and leading dashes
remain valid; `--` separates options from path arguments. A symlink that resolves outside the root
is denied.

`raw` and `published` are immutable by default. Safe write creates a new file and cannot overwrite.
Safe edit requires the current source SHA-256 and an inclusive line range. It stores the exact prior
bytes in the internal version area, preserves LF or CRLF endings, writes UTF-8 without BOM through
a same-directory temporary file, flushes it, and commits with an internal atomic replace. Rollback
requires both the current hash and the exact recorded version ID. These internal replaces are not a
general move capability.

## 4. Encoding and result contract

Reads are byte-bounded and decode strictly. Automatic detection checks UTF-8 BOM, UTF-16 BOM,
validated UTF-8, GBK, and GB18030 in that order. Callers may explicitly select UTF-8, GBK,
GB18030, UTF-16LE, or UTF-16BE. Invalid or ambiguous bytes return
`FILE_ENCODING_UNCERTAIN`; replacement decoding is forbidden. Original bytes and their SHA-256
remain unchanged, while text returned to agent context is normalized Unicode with
`normalized_encoding=utf-8`.

Every result carries the ToolResult call/task/run/scope identity, command ID, executable hash when
applicable, literal relative path, byte and line counts, source and normalized encoding, detector
confidence, input and output hashes, exit state, duration, and completion time. Denials carry a
stable error code and next action. Output bytes and lines are limited before context entry.

## 5. Platform and deferred boundaries

The local Windows profile uses the detected Git for Windows UTF-8 command binaries directly, not
CMD translation. CI and reference deployment use Linux command binaries. Exact executable hashes
are environment evidence and must be republished after an upgrade.

Durable version manifests, artifact-store preservation, directory creation, recursive find,
bounded range readers, additional registered parsers, and production worker packaging may extend
this contract later. They must retain the same fixed-template, scope, hash, budget, and audit
invariants. Formal TG-03 closure still requires the complete frozen Chinese-path corpus and an
approved immutable runtime candidate.
