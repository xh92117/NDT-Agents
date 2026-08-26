# Reference Adapters V1

**Task:** S5-08 six-method reference simulator integration

**Contract version:** 1.0.0

**Required tests:** INT-INSTRUMENT, UNIT-TOOLREG, SEC-TOOLS, SEC-TENANT, BUDGET, OBS-AUDIT, QUICK, DOC

## 1. Boundary

This contract publishes one deterministic reference simulator for each registered V1 method: AE,
GPR, IE, MV, RT, and UT. It integrates the S4-05 method definitions, S5-05 adapter SDK and Tool
Registry path, and S5-06 canonical inspection-data contract. It does not emulate vendor protocols,
claim signal-processing quality, contact a process or device, or create formal inspection evidence.

## 2. Immutable profile registry

Every `ReferenceAdapterProfile@1.0.0` binds:

- one exact method code and S4-05 method-definition SHA-256;
- one exact local simulator transport binding and S5-05 adapter-registration SHA-256;
- one application-owned fixture identity, version, and SHA-256;
- the S5-06 canonical contract version;
- expected signal dimension and unit, calibration kind, acquisition setting names, parser, device,
  adapter, and fixture identities;
- one canonical profile SHA-256.

The registry contains exactly six profiles in AE, GPR, IE, MV, RT, and UT order and has one
deterministic snapshot hash. Duplicate, missing, unknown, stale, cross-method, unsupported signal,
incomplete acquisition, invalid calibration, changed registration, or tampered profile content is
not publishable.

## 3. Shared execution path

Each generated Tool Registry definition is task-scoped, local-destination, read-only,
network-free, credential-free, permission-gated, bounded, and audited. The strict input exposes only
one registered fixture identity. The caller cannot choose a method, transport, command, executable,
endpoint, path, parser, device, calibration, artifact, or result identity.

An accepted invocation consumes one physical-tool call and invokes one injected deterministic
provider once. The provider returns a bounded canonical UTF-8 payload plus the exact manifest,
profile, fixture, and registration hashes. The S5-05 adapter wrapper validates provider identity,
strict output, device/calibration provenance, bytes, timeout, and evidence before returning an
untrusted review-required envelope.

The reference consumer then parses the payload through S5-06 and verifies exact scope, method,
simulated origin, manifest, profile, fixture, registration, adapter, device, calibration, parser,
signal, and acquisition identity. The canonical result must be processing-eligible and formally
ineligible. A successful result remains untrusted and review-required.

## 4. Failure and safety rules

Wrong scope, user, task, run, permission, registry, profile, fixture, or registration; caller-selected
method or transport; malformed, non-UTF-8, non-canonical, oversized, or hash-changed output; wrong
method, origin, signal, settings, artifact scope, adapter, device, calibration, or parser; provider
identity/error/timeout; and budget exhaustion return typed non-fabricated failures. Preflight
denials make zero provider calls. Post-call failure preserves the S5-05 ToolResult and audit evidence.
There is no retry or fallback.

Local tests make zero LLM, network, secret, command, subprocess, simulator-process, real-instrument,
device, approval, publication, or formal-conclusion calls. One in-process fixture-provider call is
counted as one physical tool call so production adapters cannot bypass the common meter.

## 5. Production replacement

A real adapter must publish a new transport binding, registration, parser, device, calibration,
fixture or source-data policy, tests, and registry snapshot. It must not reuse a reference-simulator
identity or represent deterministic fixture evidence as laboratory or production evidence. Hardware
deployment also requires authorized samples, qualified calibration and operator evidence, vendor
interface and license review, live security and failure tests, immutable CI, and TG-05 approval.
