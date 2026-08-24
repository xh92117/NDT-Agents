# S0-05 Personal Runtime Evidence

## Scope

- Task: S0-05 isolated continuation while S0-10 remains blocked
- Branch: `codex/s0-05-personal-runtime`
- Base commit: `4a9254bce37289af3ed42da0769375dc93a8bc8d`
- Data: public or synthetic only
- Production eligibility: false

This file is engineering evidence, not an approval record.

## Observed owner workstation

Read-only Windows CIM, Docker CLI, and `nvidia-smi` inspection recorded:

- Windows 11 Home 64-bit;
- Intel i7-1355U, ten physical and 12 logical cores;
- 15.64 GiB RAM;
- NVIDIA RTX 2050, 4,096 MiB VRAM, driver 595.95;
- 204.63 GiB free on the workspace volume;
- Python 3.12.13 and uv 0.11.20; and
- Docker client 29.7.2 with no available engine.

The host passed the complete repository test profile. It does not meet the 32 GiB `DEV-CPU-1`
proposal and is not evidence for MinerU throughput or local-LLM sizing.

## Provider feasibility

Official OpenAI documentation retrieved on 2026-08-24 records the Responses request controls and
current model guidance. It describes `gpt-5.6-terra` as the balance-of-intelligence-and-cost route.
The official supported-country page did not list Mainland China and warns that access outside the
list may lead to account blocking or suspension. Therefore the direct OpenAI candidate is
`BLOCKED_UNSUPPORTED_CURRENT_JURISDICTION`, no key was requested, and no call was attempted.

The owner offered access to a China-region model API while this work was running. The candidate is
recorded as `AWAITING_NON_SECRET_PROVIDER_METADATA`. Provider/model name, official documentation,
protocol, processing and storage location, retention and training policy, and commercial terms are
required before a key is accepted through a local secret reference or any physical call occurs.

The local vLLM route remains deferred because no exact model, weights, license, quantization,
context, concurrency target, or GPU benchmark is frozen. The only selected route is the offline
deterministic fake with public or synthetic data.

## Exact hashes

| Artifact | SHA-256 |
|---|---|
| `security/personal-project-governance.v1.json` | `c649dfa59ec6cc94c2bd80ea8f9f24699a10d9af36e033a3bc87a80f9a63b083` |
| `architecture/personal-development-runtime.v1.json` | `adad384a90661d5a9e29d492a810520fc738cc99848494343a408b49b0ad879f` |
| `docs/decisions/ADR-0001-reference-runtime.md` | `240cc3f78d73901254cf532543043badc4e2aa56848e821be578b9b0c02e0b45` |
| `tools/provider_smoke.py` | `9164fe224636ae5663e56a63abb60a3c6c88aa09c5f7152bcc44159d7331aa03` |

## Offline provider smoke

Command:

```text
uv run python tools/provider_smoke.py
```

Result: `PASS`. Strict request, structured output, allowlisted synthetic function arguments,
unknown-field rejection, output-token and timeout limits, typed timeout/cancellation/refusal/
incomplete/rate-limit states, provider/model/endpoint/region/retention metadata, credential
redaction, and zero physical network calls passed. Hosted and local routes were not run.

## Local TASK validation

Commands:

```text
uv run python tools/generate_schemas.py
uv run python tools/generate_fixture_catalog.py
uv run python tools/generate_benchmarks.py
uv run python tools/generate_sbom.py
uv run pytest -q
uv run ruff check src tools tests
uv run ruff format --check src tools tests
uv run mypy
uv run python tools/check_controlled_docs.py
PYTHONUTF8=1 uv run pip-audit --local --progress-spinner off
```

Result: all four generators produced zero tracked drift; 27 targeted tests and all 239 tests
passed; Ruff passed; 79 files were formatted; strict mypy found no issues in 79 source files;
DOC 1.29 passed for four ASCII controlled documents and seven gates; and the dependency audit
found no known vulnerabilities.

## Remaining blockers

S0-05 remains `BLOCKED`. The offline candidate is usable only for isolated personal development.
R-003, R-005, R-007, and R-010 remain open. A China-region physical provider smoke awaits the
non-secret provider metadata; production additionally requires exact model and endpoint versions,
contract and license review, cost and quota evidence, approved data handling, benchmark results,
rollback, and accountable approvals.
