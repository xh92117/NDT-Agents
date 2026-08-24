# Memory Restore V1

**Contract version:** 1.0.0  
**Task:** S2-06  
**Status:** isolated provider-neutral implementation

Immutable snapshots bind task and exact user scope, source branch, checkpoint, graph and state
versions, canonical state hash, memory IDs, up to 20 project facts, ten artifact references, six
required turns, and at most 6,000 injection tokens. Snapshot IDs cannot be overwritten.

Direct restore selects one exact snapshot. Intent restore searches only visible snapshots, returns
at most five ordered candidates, and automatically creates a preview only when the top score is at
least 0.90 and exceeds the second by at least 0.12. Ambiguous results remain user choices.

Every path rechecks scope, permission version, state compatibility, checkpoint binding, hashes,
artifact availability, and injection limits. A material restore requires an immutable hash-bound
preview and explicit confirm or cancel. Confirmation creates a deterministic new branch with the
snapshot branch as parent; it never overwrites current work. Terminal decisions are append-only,
idempotent for the same outcome, and reject conflicting outcomes.

PostgreSQL snapshot and restore-event tables use exact user scope, forced RLS, append-only
triggers, and reversible migration.
