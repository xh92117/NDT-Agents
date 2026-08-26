# S6-05 Security and Resilience Assessment

## Candidate

- Date: 2026-08-25
- Branch: `codex/s6-clients`
- Base commit: `16c0c6871b23be6fc03416bdec38adfc85d7d1b9`
- Candidate state: mutable local working tree
- Assurance source SHA-256: `848c7618e097b9d1b9a38d251b3a9006ceb18a87502b570032be3c3bf539599e`

## Local automated result

The versioned assurance catalog contains 11 required cases: seven automated cases and four external
cases for live infrastructure, hardware disconnects, and independent penetration testing. The local
aggregator is fail closed for missing cases, stale build/catalog binding, P0/P1 findings, tenant
leaks, duplicate committed side effects, retry-limit violations, and incomplete failure explanation.

| Check | Result |
|---|---|
| assurance aggregation contract | 13 passed |
| selected security, isolation, tool, model, lifecycle, audit, approval, recovery, and storage suite | 474 collected; 473 passed, 1 documented Windows path skip |
| dependency vulnerability audit | `pip-audit 2.10.1 --local --strict`; no known vulnerabilities found |
| high-confidence secret scan | zero private-key, AWS, GitHub-token, or Slack-token patterns |

The first `pip-audit` attempt failed because `pip_api` decoded a Windows path using UTF-8 while the
process emitted the localized path in another encoding. Re-running with `PYTHONUTF8=1` and
`PYTHONIOENCODING=utf-8` succeeded. This is preserved as Windows/Chinese-path diagnostic evidence,
not hidden as a clean first attempt. `gitleaks` is not installed, so the repository does not claim a
gitleaks scan.

## Local invariants

- Tenant leaks: 0 in the automated suite.
- Duplicate committed side effects: 0 in the automated suite.
- Open automated P0/P1 findings: 0.
- Hidden or unbounded retries found: 0.
- Unrepaired deterministic failure explanation coverage: 100 percent in exercised cases.
- Dependency vulnerabilities reported by the available audit: 0.

## External blockers

S6-05 is `BLOCKED` for release purposes until these catalog cases run against the exact immutable
candidate:

- `S6SEC-008`: live database and object-store failover;
- `S6SEC-009`: live identity, KMS, queue, cache, and index faults;
- `S6SEC-010`: authorized hardware/instrument disconnect;
- `S6SEC-011`: independent penetration test.

Production-like RLS, storage encryption, network partition, disk-full, image scanning, independent
SAST/DAST/fuzzing, and accountable residual-risk approval are also absent. Local green evidence does
not satisfy these cases.
