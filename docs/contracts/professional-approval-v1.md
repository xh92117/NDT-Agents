# Professional Approval V1

## Purpose

S4-07 extends the S1-13 generic approval service with strict professional preconditions for
inspection plans, inspection reports, and critical findings. The wrapper does not duplicate the
append-only event journal, decision state machine, audit trail, delegation, expiry, idempotency, or
one-time resume grant.

## Policy roles

`professional-approval-policy-1.0.0` preserves all generic approval kinds and assigns separate
professional roles:

- plan approval: `QUALIFIED_PLAN_APPROVER`, with bounded delegation;
- report approval: `QUALIFIED_REPORT_APPROVER`, without delegation;
- critical-finding confirmation: `QUALIFIED_FINDING_APPROVER`, without delegation.

The generic S1-13 service continues to deny requester self-approval, cross-scope or stale-permission
actors, missing roles, stale hashes, duplicate actors, conflicting idempotency IDs, expired or
terminal decisions, and resume replay.

## Plan and report candidates

A plan checkpoint requires a strict hash-valid S4-02 result in `SUCCESS`, with zero unresolved
issues, mandatory review, approval `PENDING`, and formal use forbidden. A report checkpoint requires
the same S4-03 boundaries plus a preliminary non-formal conclusion and no unresolved critical or
human-confirmation finding. Both require an exact `PASS` S4-06 assessment and a completed
aggregation-ready S1-09 workflow whose reviewed child envelope binds exactly that result.

Plan approval binds the plan result and plan-content hashes. It does not approve a report or allow
formal use. Report approval binds the report result, report-content hash, report ID, and revision.
It does not change `formal_release_allowed`; formal responsibility and accreditation remain blocked
by R-004 until separately approved.

## Critical-finding candidates

A critical-finding checkpoint is created only from an exact strict report in `HUMAN_REQUIRED`. The
selected IDs must be non-empty, sorted, unique, present in the report, `CRITICAL`, and explicitly
human-confirmation-required. The checkpoint requires the exact S4-06 `HUMAN_REQUIRED` assessment
and S1-09 human-required pause, not a fabricated pass.

Each selected finding binds hashes for statement, limitations, observations, calculations, plan
bases, and evidence references. Confirmation does not silently mutate the report; its one-time
resume grant is evidence for the responsible workflow to perform a bounded correction and re-review.
A critical report cannot enter the ordinary report-approval path.

## Hash-bound checkpoint

`ProfessionalApprovalBinding@1.0.0` binds exact scope/task, kind, action, target type/ID/version,
professional result kind, result and content hashes, review envelope, assessment and review-manifest
hashes, review decision, and any critical-finding bindings. Its canonical subject hash becomes the
generic approval candidate hash. The generic preview contains only this binding and a hash-only
summary, not the full report or evidence.

`ProfessionalApprovalCheckpoint@1.0.0` revalidates the binding against the generic approval status,
professional policy version, subject hash, and its own checkpoint hash. It records literal zero
model, tool, network, publication, and user-delivery calls.

Only a current approved subject can consume one exact S1-13 resume grant. Exact replay of the same
resume ID returns the same grant; another resume ID is denied. The wrapper performs no model, tool,
network, report mutation, formal conclusion, publication, or user-delivery action.
