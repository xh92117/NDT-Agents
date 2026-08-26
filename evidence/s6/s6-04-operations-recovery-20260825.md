# S6-04 Operations and Recovery Evidence

## Candidate and governance

- Date: 2026-08-25
- Branch: `codex/s6-clients`
- Base commit: `16c0c6871b23be6fc03416bdec38adfc85d7d1b9`
- Security baseline SHA-256: `90315dd61e1c378addf6d6e20186de75ef865a8b0782df0c97fde7c20b774bed`
- Governance: provisional personal pre-commercial engineering targets
- Independent approval: not satisfied
- Live recovery environment: not available

## Delivered local controls

- Strict provisional/approved operations profile with exact security-baseline, metric, environment,
  quota, backup retention, RPO, RTO, zero-loss, and owner-role fields.
- Atomic exact-scope quota claims for tenant/user concurrency, daily accepted-task windows, storage,
  and request-rate windows; separate active/hard denial, idempotent release, collision protection,
  zero-negative counters, and tenant/user/project/permission/policy isolation.
- Canonical exact-scope backup manifests with immutable artifact hashes, safe KMS/Vault/HSM key
  references, checkpoint/event counters, predecessor chain, and self-hash validation.
- Deterministic restore assessment for scope, manifest/profile, chain, artifact integrity, checkpoint
  count, approval/publication zero-loss, RPO, RTO, rollback, policy approval, and environment.
- [Recovery runbook](../../docs/operations/recovery-runbook-v1.md) covering backup, restore, failover,
  rollback, degraded modes, evidence, stop rules, and approval boundaries.

## Source hashes

| File | SHA-256 |
|---|---|
| `src/ndt_agents/operations/models.py` | `77ea4547cdfd49eae8f4329469a855c0dd47225636fa5924975ac9d253af8521` |
| `src/ndt_agents/operations/service.py` | `2e73f79be30227841772795889c4ea7ddc9d07bf89d92fcd79ecca56fb5977c8` |
| `docs/operations/recovery-runbook-v1.md` | `467568589bf6f6bfabe61f3e918b47fbed988767597a876716fd66b2841e5ce5` |

## Verification

| Profile | Result |
|---|---|
| S6-04 dedicated | 15 passed |
| operations, budget, recovery, identity, lifecycle, security, and storage boundary | 90 passed |
| full regression | 946 collected; 945 passed, 1 documented Windows path skip |
| Ruff and format | passed; 351 files formatted |
| strict mypy | passed over 173 source files |
| documentation and diff | DOC 1.58 and `git diff --check` passed |
| code graph | full refresh completed without errors; 147 files parsed, 2,263 raw nodes, 19,788 raw edges |

The graph aggregate remains limited to files already visible to its Git-based index and therefore
does not yet include the untracked operations package. Direct tests and full regression are the
authoritative evidence for this mutable candidate.

## Blocking release evidence

S6-04 remains `BLOCKED`, not `DONE`, until all of the following exist:

- Operations, Quality, and Security Owners approve the exact profile and metric definitions.
- The reference environment, quota windows, alerting, and distributed atomic quota store are frozen.
- PostgreSQL, object storage, audit/approval stores, KMS, queues, caches, indexes, and real backup
  media execute backup, failover, restore, rollback, expiry, legal-hold, and degraded-mode drills.
- The measured task-state RPO, core-service RTO, noncritical RTO, and acknowledged approval/publication
  zero-loss targets pass with immutable evidence.
