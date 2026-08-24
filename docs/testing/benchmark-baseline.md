# S0 Synthetic Benchmark Baseline

## Scope

Task `S0-07` generates eight versioned JSONL data sets at `benchmarks/v1`:

| Data set | Cases | Baseline coverage |
|---|---:|---|
| routing | 1,000 | General, one professional, independent/dependent multi-agent, async, review, human required; explicit typed route signals |
| technical QA | 288 | six methods x six structure classes x eight variants; five material classes rotated |
| inspection plan | 60 | new build, in service, incident, acceptance, missing input, conflicting constraints |
| report | 40 | single/multi-method, limited data, conflicting results |
| compression and restore | 200 | C0-C3, protected fields, direct/intent/preview/branch restore |
| Bash and encoding | 300 | six encoding states x five path classes x ten variants |
| fault | 120 | 12 failure modes x ten variants |
| tenant isolation | 1,000 | ten storage/runtime layers x 100 forged-scope probes |

Every case is project-generated, synthetic, classified `INTERNAL`, excluded from training, and
assigned to `CALIBRATION`, `DEVELOPMENT_EVAL`, or `FROZEN_TEST`. Generation is deterministic; the
manifest stores file counts, split counts, and SHA-256 hashes.

## Machine gold and expert gold

Routing, compression/restore, encoding, fault, and tenant-isolation expected outcomes are
machine-checkable. Technical QA, inspection-plan, and report cases intentionally contain no
fabricated professional answer. They are marked `PENDING_DOMAIN_EXPERT_GOLD` and cannot satisfy a
quality threshold until authorized experts add rubric-bound gold results using licensed sources.

Routing cases contain discriminative synthetic request intent and explicit `route_signals` for
general eligibility, the minimum professional assignments, dependencies, and human requirement.
The expected route remains separate. Runtime tests must not use case ID, request number, split, or
the expected object as a feature. The repaired routing file SHA-256 is
`129ea5fbd73408670cd3257db376230d16d584130a1b63e6c6cf756eef66f453` and the current manifest
SHA-256 is `bb5768976ab8d2214c2e2aa2de9579af3e6f46adb023cb407e971f1dae909908`.

## Reproduction

```text
uv run python tools/generate_benchmarks.py
uv run pytest tests/baseline/test_benchmark_manifest.py
```

The current manifest state is `PENDING_EXPERT_ADJUDICATION_AND_REAL_DATA`. S0-07 remains blocked by
the S0-06 real-data/rights gap and the missing expert adjudication even when deterministic count,
coverage, rights, split, and integrity tests pass.
