# Security, Compliance, Supply-Chain, and Service Baseline

## 1. Document status

| Field | Value |
|---|---|
| Baseline version | `1.0.0` |
| Task | `S0-10` |
| State | `PROPOSED_FOR_HUMAN_APPROVAL` |
| Machine-readable source | `security/security-baseline.v1.json` |
| Required approvers | Security Owner, Legal Owner, Operations Owner, Quality Owner |

This baseline is an implementable engineering proposal. Automated checks can establish its
completeness and internal consistency, but cannot grant organizational, legal, accreditation, or
production approval. Production use remains blocked until the required approvers record decisions
against this exact version and hash.

## 2. Security objectives

1. Deny access by default and bind every request and stored object to tenant and project scope.
2. Keep the Main Agent as the only holder of complete user-facing state.
3. Treat uploaded files, retrieved text, model output, tool output, and external services as
   untrusted.
4. Prevent autonomous publication, destructive data actions, formal conclusions, and high-impact
   physical commands.
5. Preserve immutable, attributable evidence for authorization, model, tool, review, approval, and
   publication events.
6. Fail explicitly and safely when identity, policy, keys, audit, storage, or review is unavailable.

## 3. Critical assets and trust boundaries

Critical assets are identity and permission claims, tenant data, raw inspection data, standards and
licensed knowledge, prompts and Skills, model/provider credentials, encryption keys, tool policies,
approvals, audit events, checkpoints, published artifacts, SBOMs, and release signatures.

```text
Untrusted user/client
  -> TB-01 API and identity edge
     -> TB-02 tenant-scoped application and Main Agent
        -> TB-03 isolated child-agent execution
        -> TB-04 policy-enforced Tool Registry
           -> TB-05 local process/instrument boundary
           -> TB-06 external model, Web, MCP, and API boundary
        -> TB-07 data plane: SQL, vector, cache, queue, object, backup
        -> TB-08 approval and immutable audit plane
  -> TB-09 build, dependency, container, model, and release supply chain
```

No boundary inherits trust from network location. Identity, scope, permission version, contract
version, input, output, budget, and audit requirements are revalidated at every boundary.

## 4. Threat treatment

| Threat | Risk | Required treatment | Owner | Implementation | Verification |
|---|---|---|---|---|---|
| forged scope or cross-tenant retrieval | critical | OIDC, deny-by-default RBAC, RLS, scoped vector/cache/object keys | Security Owner | S1-03 | SEC-TENANT |
| prompt injection through files, Web, or tool output | high | provenance labels, instruction/data separation, tool policy, output validation | Agent Security Owner | S1-04, S2-01, S5-01 | SEC-TOOLS, SEC-ALL |
| arbitrary command or unsafe file mutation | critical | registered argument-array commands, fixed roots, immutable raw input, approval | Tool Owner | S3-02 | SEC-BASH |
| secret disclosure to prompts, logs, artifacts, or providers | critical | managed secret references, redaction, egress policy, key separation | Security Owner | S1-11 | SEC-PLATFORM |
| approval spoofing, replay, or target substitution | critical | authenticated dual control and decision bound to target hash/version | Quality Owner | S1-13 | INT-APPROVAL, SEC-PLATFORM |
| audit alteration or evidence loss | critical | append-only records, hashes, restricted export, retention, backup | Audit Owner | S1-10 | SEC-ALL, RES-CHECKPOINT |
| malicious or vulnerable dependency/model | high | pinned lock, SBOM, provenance, scan, license decision, replacement path | Supply-Chain Owner | S0-08, S5-07 | SEC-BASELINE, SEC-ALL |
| destructive deletion or legal-hold bypass | critical | eligibility check, dual approval, tombstone, backup expiry, erasure audit | Data Governance Owner | S2-09 | INT-DATA-LIFECYCLE |
| unreviewed formal conclusion or physical action | critical | mandatory human approval and immutable evidence | Quality Owner | S1-13, S4-07, S5-08 | INT-APPROVAL, SEC-TOOLS |
| resource exhaustion or unbounded agent loop | high | per-task hard budgets, concurrency quotas, cancellation, no-progress guard | Operations Owner | S1-08 | BUDGET, RES-ALL |
| provider outage or malformed asynchronous result | high | timeout, circuit breaker, typed partial result, checkpoint, alternative adapter | Operations Owner | S1-07, S5-01 | RES-CHECKPOINT, RES-ALL |
| unsafe or malformed uploaded content | high | size/MIME/hash inspection, parser isolation, malware policy, manual review | Knowledge Owner | S3-03 | INT-KNOWLEDGE, SEC-ALL |

Residual critical risk is not accepted by this document. A required control that is unavailable
forces `BLOCKED`, `DENIED`, or `HUMAN_REQUIRED`; it does not silently downgrade protection.

## 5. Data classification and handling

| Class | Examples | Minimum handling |
|---|---|---|
| PUBLIC | approved public product documentation | integrity hash; publication approval still applies |
| INTERNAL | synthetic tests, non-sensitive operating metadata | tenant scope; TLS; encryption at rest; controlled logs |
| CONFIDENTIAL | customer documents, inspection data, reports, project memory | least privilege; scoped storage; no provider use without policy; encrypted export |
| RESTRICTED | credentials, key material, legal holds, safety-critical unpublished findings | dedicated secret/key store or restricted evidence store; dual control; never in prompts or general logs |

Classification follows the highest-class input and may be raised by policy. Derived data,
embeddings, caches, traces, checkpoints, and backups inherit source restrictions. Downgrading
requires an authorized decision and an audit record.

## 6. Encryption, keys, and secrets

- External and internal service traffic uses TLS 1.2 or later; TLS 1.3 is preferred. Certificate
  validation is mandatory.
- Databases, object storage, queues, vector stores, backups, and portable confidential artifacts
  use AES-256 or an approved managed-service equivalent at rest.
- Development, test, staging, and production keys are separate. Tenant-specific keys are used when
  required by contract or policy.
- Applications receive short-lived identity-bound credentials; long-lived secrets do not enter
  source, fixtures, prompts, traces, or logs.
- Rotation, revocation, unavailable-key behavior, audit, and cryptographic-erasure procedures are
  tested before production.
- A key identifier may be stored in a contract; raw key material may not.

## 7. Retention, deletion, and legal hold

The values below are technical defaults, not jurisdiction-specific legal advice. Contractual or
legal periods override them only through an approved policy version.

| Data class | Proposed default | Rule |
|---|---:|---|
| transient task scratch | 30 days after task close | delete if no hold, approval, incident, or checkpoint dependency |
| deterministic cache | 24 hours maximum | invalidate earlier on scope, permission, source, policy, or version change |
| operational telemetry | 90 days hot, 365 days archive | redact content and credentials before collection |
| security and approval audit | 7 years | immutable; organization must confirm jurisdiction and accreditation needs |
| project evidence and reports | organization-defined | no automatic deletion until an approved project policy exists |
| backups | 35 days rolling | held data and immutable evidence follow the approved exception procedure |

Export and deletion must cover SQL, vector, cache, queue, object, memory, snapshot, artifact, log,
and backup indexes. Legal hold is checked before mutation. Authorized deletion creates an immutable
tombstone and makes data unrecoverable after documented backup expiry or cryptographic erasure.

## 8. Supply-chain and license controls

- Pin direct dependencies and retain a deterministic lock file.
- Produce a CycloneDX or SPDX SBOM for code, containers, models, parsers, OCR components, and model
  weights before release.
- Record package/model name, version, source, hash, license, notices, commercial-use constraints,
  data-location constraints, known vulnerabilities, owner, decision, and replacement path.
- Block release for unknown, incompatible, unreviewed, or prohibited obligations.
- Verify artifact provenance and signatures where available; scan source, dependency, container,
  secret, and infrastructure definitions in CI.
- Legal and Security Owners approve obligations. Automated metadata is evidence, not legal approval.

## 9. Incident response

The Security Incident Commander owns classification and containment. Operations owns service
isolation and recovery. Data Governance owns affected-scope analysis. Legal owns notification
criteria. Quality owns conclusions and released-report impact.

For a suspected cross-tenant leak, credential exposure, unauthorized mutation, evidence integrity
failure, or unsafe physical command: stop the affected path, revoke access, preserve immutable
evidence, isolate caches and queues, identify impacted scopes, notify required owners, recover from
a verified state, and document corrective actions. Evidence preservation must not copy protected
data to an unauthorized scope.

## 10. Initial SLI/SLO and recovery proposal

These objectives apply only after an Operations Owner approves the exact measurement definitions
and reference environment. They are initial engineering targets, not an existing service claim.

| SLI | Formula and window | Proposed objective |
|---|---|---:|
| API availability | successful eligible API minutes / eligible API minutes, calendar month | >= 99.5% |
| accepted-task durability | accepted tasks recoverable from committed state / accepted tasks, calendar month | >= 99.9% |
| interactive acknowledgement latency | P95 time from accepted request to task ID or typed rejection, 5-minute buckets | <= 2 seconds |
| authorization correctness | unauthorized successful actions / authorization probes | 0 |
| audit completeness | required auditable events with valid identity, scope, hashes, time, and outcome / required events | 100% |
| critical evidence integrity | verified critical artifact hashes / sampled critical artifacts | 100% |

The proposed monthly availability error budget is 0.5 percent of eligible API minutes. Security,
tenant-isolation, approval-integrity, and critical-evidence failures have zero error budget and stop
the affected release or service path.

- Proposed RPO: 15 minutes for committed task state and tenant metadata; zero committed-event loss
  for approval and publication records after acknowledgment.
- Proposed RTO: 4 hours for the core task service and 24 hours for non-critical analytics.
- Reference measurement environment: to be frozen in `S0-05`; load profiles are versioned and
  exclude planned maintenance only when announced and approved before the event.

## 11. Degraded modes

| Failed dependency | Allowed behavior | Forbidden behavior |
|---|---|---|
| identity or policy | health diagnostics only | accept or continue tenant work |
| audit or approval store | read-only access where policy permits | mutation, publication, formal conclusion, physical action |
| model provider | deterministic validation, queued retry, or typed partial result | fabricate completion or bypass review |
| vector retrieval | exact approved-source lookup if available, otherwise explicit partial result | uncited technical conclusion |
| cache | bypass and recompute within budget | cross-scope fallback cache |
| artifact store | preserve task/checkpoint metadata and retry safely | publish a missing or unverified artifact |
| key or secret service | public health response and typed failure | plaintext fallback or embedded credential |

## 12. Approval and change control

The machine-readable baseline must pass `SEC-BASELINE` before human review. The Security Owner,
Legal Owner, Operations Owner, and Quality Owner then approve or reject the exact baseline version
and hash. A change to threats, classifications, retention, encryption, secrets, dependency/model
license policy, SLO, RPO/RTO, or degraded modes creates a new version and reruns affected tests.

