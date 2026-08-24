# Role, Scope, Approval, and Liability Baseline

**Control ID:** GOV-ROLE-1.0  
**Task:** S0-01  
**Status:** APPROVED_FOR_DEVELOPMENT  
**Production accreditation status:** UNRESOLVED

## 1. Scope hierarchy

All requests and persistent objects are evaluated in this order:

```text
organization
  -> tenant
      -> project
          -> user and role membership
              -> task
                  -> child run, tool call, artifact, memory, or approval
```

- A tenant is the highest business-data isolation boundary.
- A project is a mandatory boundary for project data, knowledge, tasks, memory, cache, and artifacts.
- A user may hold different roles in different tenants and projects.
- A role assignment is versioned and carries activation and expiry times.
- An administrator has no implicit right to inspect another tenant or project.
- Break-glass access is disabled in V1 until a separately approved policy and implementation exist.

## 2. Human roles

| Role | Core responsibility | Allowed high-level actions | Explicitly prohibited |
|---|---|---|---|
| Platform Owner | Operate the shared platform | configure global services; approve releases with Security and Quality | read tenant business data without a scoped support approval |
| Tenant Administrator | Manage tenant membership and tenant policy | create projects; assign tenant roles; view tenant audit summaries | approve own formal technical output; cross-tenant access |
| Project Administrator | Manage one project | assign project members; configure project policy and templates | override tenant policy; approve own technical output |
| NDT Engineer | Define inspection work and interpret evidence | create plans; review source data; draft findings and reports | self-approve a formal report; issue conclusions outside qualifications |
| Data Processing Specialist | Process source inspection data | run approved parsers, algorithms, and models; create processing artifacts | change raw input; publish a formal conclusion |
| Knowledge Curator | Prepare knowledge candidates | ingest, normalize, classify, and submit knowledge for review | publish, replace, withdraw, or roll back without approval |
| Independent Reviewer | Review complex technical output | return PASS, REVISE, CONFLICT, HUMAN_REQUIRED, or FAILED | modify raw evidence; approve work when independence is compromised |
| Qualified Approver | Make accountable human decisions | approve or reject knowledge, plans, reports, critical findings, and formal conclusions within qualification | approve own authored or processed result; approve outside scope or after expiry |
| Integration Operator | Manage registered adapters and devices | register approved tool or simulator versions; run authorized maintenance | issue a production device action without task and approval scope |
| Security Auditor | Inspect policy and audit evidence | read scoped security, policy, and audit records | alter business output, approval, or immutable audit evidence |
| Read-only User | Consume approved outputs | read authorized published content and completed task results | invoke mutating tools or approve work |

## 3. Product-agent responsibilities

| Actor | Receives full user task state | May call tools | May publish or approve | May communicate with user |
|---|---:|---:|---:|---:|
| Main Agent | yes | no | no | yes |
| General Agent | no | allowed registry subset | no | no |
| Professional Agent | no | allowed registry subset | no | no |
| Review Agent | no | read-only by default | recommendation only | no |
| Knowledge Agent | no | ingestion subset | no | no |
| Deterministic runtime | scoped state only | executes authorized calls | enforces approval | no |

No product agent is a legal person, qualified signatory, accredited inspection body, or substitute for a responsible engineer. Agent output remains advisory until an authorized human decision is attached to the exact artifact and evidence hashes.

## 4. Approval matrix

| Action | Requester | Required approver | Separation of duty | Default when missing |
|---|---|---|---|---|
| Publish, replace, withdraw, or roll back knowledge | Knowledge Curator | Qualified Approver or Knowledge Owner | approver did not author the candidate | deny and keep candidate unpublished |
| Approve an inspection plan | NDT Engineer | Qualified Approver | approver did not author the plan | keep DRAFT |
| Release a formal report or critical finding | NDT Engineer | Qualified Approver | independent review plus non-author approver | block formal release |
| Execute a high-impact physical device command | Integration Operator or NDT Engineer | device-authorized Qualified Approver | requester and approver differ | do not execute |
| Perform a destructive data-lifecycle action | Project Administrator | Tenant Administrator plus policy engine | requester and approver differ; legal hold checked | do not mutate |
| Grant privileged tenant access | Tenant Administrator | second Tenant Administrator or Platform Security Owner | dual control | do not grant |
| Publish a commercial software release | Platform Owner | Security Owner and Quality Owner | release candidate hashes are immutable | do not publish |

Approvals bind tenant, project, actor, action, target version, target hashes, policy version, reason, time, expiry, and outcome. Replayed, expired, stale, or mismatched approvals are rejected.

## 5. Responsibility and liability boundaries

- The platform preserves evidence and explains uncertainty; it does not claim accreditation.
- A formal conclusion requires traceability to source data, calibration, processing version, model or algorithm version, standard clause, reviewer, and qualified approver.
- A user remains responsible for lawful source rights, correct field acquisition, device safety, and professional use of output.
- The platform owner is responsible for access control, isolation, auditability, recovery, and accurate disclosure of system limitations.
- A qualified organization remains responsible for defining applicable standards, qualification rules, signatory authority, retention periods, and jurisdiction-specific report wording.

## 6. Unresolved production decisions

The following decisions block formal production publication but do not block development with synthetic data:

1. The accreditation and legal-signature boundary for each target region.
2. The qualification registry and evidence required for a Qualified Approver.
3. Organization-specific retention and legal-hold periods.
4. Professional indemnity and contractual allocation of responsibility.

These decisions are tracked by risk R-004. Production policy remains deny-by-default until the Product and Quality Owner records an approved replacement for this section.
