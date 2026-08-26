# S6 Operations and Recovery Runbook V1

## Status and authority

This runbook implements the S6-04 local contract boundary. The current profile values are provisional
engineering targets inherited from `security/security-baseline.v1.json`; they are not approved SLO,
RPO, RTO, production, or commercial claims. Only Operations, Quality, and Security Owners may approve
an exact hash-bound profile after independent review.

## Targets awaiting approval

| Control | Provisional target |
|---|---:|
| API availability | 99.5 percent per calendar month |
| accepted-task durability | 99.9 percent per calendar month |
| task-state RPO | 15 minutes |
| core task-service RTO | 240 minutes |
| noncritical analytics RTO | 1,440 minutes |
| rolling backup retention | 35 days |
| acknowledged approval/publication loss | zero |

Quota active limits are normal operating capacity. Hard limits are non-overridable safety ceilings.
Any change requires a new policy version, metric review, load evidence, and approval record.

## Backup procedure

1. Freeze the exact operations profile, security baseline, schema, migration, application, parser,
   prompt, Skill, model, tool, and key-reference versions.
2. Start one exact tenant/project backup transaction or application-consistent snapshot.
3. Record every included store, immutable artifact ID, size, SHA-256, non-secret encryption-key
   reference, committed checkpoint count, and acknowledged event count.
4. Link the prior manifest hash, serialize canonically, compute the manifest hash, and store the
   manifest in immutable audit storage separate from the backed-up data.
5. Verify decryption authority without exporting key material. Sample every critical store and all
   approval/publication records. A missing artifact, hash mismatch, chain gap, or unknown key stops
   the backup from becoming a recovery candidate.
6. Enforce retention and legal hold. Expiry removes only backups proven eligible under S2 lifecycle
   policy; it never bypasses a hold or deletes immutable evidence required by policy.

## Restore and failover procedure

1. Declare the incident or drill, scope, owner, target environment, restore point, and stop conditions.
2. Isolate the failed environment and preserve logs, audit chains, manifests, hashes, and side-effect
   records. Revoke exposed credentials before recovery.
3. Verify the selected manifest and every predecessor link. Restore into an isolated destination with
   the exact compatible application and migration versions.
4. Reapply tenant/RLS policies before opening access. Recompute every restored artifact hash and
   compare checkpoint and event counts, including zero-loss approval and publication categories.
5. Measure recovery point from the last committed recoverable task state and recovery time from the
   declared start until the core service passes scoped read/write, audit, approval, and idempotency
   probes.
6. Exercise rollback before traffic movement. If identity, policy, audit, approval, artifact, key, or
   integrity checks fail, remain read-only or unavailable according to degraded-mode policy.
7. Move traffic only after the exact approved profile passes. Preserve immutable commands, actor,
   times, versions, hashes, measurements, exceptions, and final decision.

## Degraded modes and stop rules

- Identity or policy unavailable: public health diagnostics only; no tenant work.
- Audit or approval store unavailable: permitted reads only; no mutation, approval, publication,
  formal conclusion, or physical action.
- Artifact or key service unavailable: preserve task metadata and stop publication; never use
  plaintext or an unverified artifact.
- Quota store unavailable or inconsistent: deny new guarded actions; reconcile from audit evidence.
- Cross-tenant result, duplicate committed side effect, approval/publication loss, manifest-chain gap,
  hash mismatch, missed hard limit, or unknown rollback state stops recovery and release immediately.

## Acceptance evidence

Record the exact profile and baseline hashes, environment, backup and predecessor manifest hashes,
store snapshots, key references, artifact comparisons, checkpoint/event counts, RPO/RTO observations,
quota and failure probes, rollback result, degraded-mode result, responsible actors, review, approval,
and evidence URI. Synthetic local evidence must be marked `BLOCKED`, never `PASS`.
