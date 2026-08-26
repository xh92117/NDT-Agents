# Seven-Day Shadow Deployment and Expert Pilot V1

## Entry conditions

The exact S6-05 assurance assessment, S6-06 reference benchmark, and S6-07 production budget
profile must pass before a live day is recorded. The deployed build, profiles, configuration,
workload, identity environment, and owners must be immutable and approved.

## Daily evidence

Record one entry per UTC service date. Bind start and end time, workload and workflow counts, all
assigned S6 test-group states, safety counts, immutable evidence URI and hash, and the prior record
hash. A replacement entry creates a new candidate ledger; it does not edit published evidence.

Stop immediately for a P0/P1, tenant leak, duplicate committed side effect, correctness or isolation
failure, broken evidence binding, or unsafe physical/formal action. Preserve the evidence and follow
the S6-04 recovery runbook.

## Completion

Seven consecutive dates and six full elapsed 24-hour periods are mandatory. Critical workflows pass
at 100 percent and noncritical workflows pass at 98 percent or better. Every assigned daily gate is
PASS. Distinct qualified experts then assess the exact ledger against the approved rubric and record
acceptance or rejection with hash-bound evidence.

Local or synthetic records can test the evaluator but never count as a live service day. S6-08
remains blocked until real elapsed time, production-like operations, and expert evidence exist.
