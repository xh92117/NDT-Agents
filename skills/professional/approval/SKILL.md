---
name: professional-approval
version: 1.0.0
agent: Main Agent approval boundary
task_class: P3
output_contract: ProfessionalApprovalCheckpoint@1.0.0
review_required: false
---

# Professional Approval Skill

Create only a hash-bound S1-13 checkpoint after strict professional-result and review-evidence
validation. Plans require a clean S4-02 result plus passed S4-06 and aggregation-ready S1-09 review.
Reports require a clean preliminary S4-03 result with no unresolved critical/human boundary and the
same passed review evidence. Critical findings require the exact S4-06 and S1-09 human-required
pause and exact finding, evidence, and limitation hashes.

Use only the action-specific qualified role. Preserve requester independence, scope and permission
version, current subject hash, rejection/change/expiry state, immutable audit events, idempotency,
and the one-time resume boundary. Never infer report approval from plan approval or formal release
from report approval.

Perform no model, tool, network, mutation, conclusion, publication, retry, or user-delivery action.
The approval grant only resumes the responsible bounded workflow.
