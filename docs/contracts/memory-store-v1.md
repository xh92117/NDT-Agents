# Memory Store V1

**Contract version:** 1.0.0  
**Task:** S2-04  
**Status:** isolated provider-neutral implementation

`MemoryStore` separates `RUNTIME`, `SESSION`, `USER`, `PROJECT`, and `AUDIT` records. Every
immutable record binds tenant scope, namespace, canonical content hash, provenance, confidence,
classification, approval state, protected state, source version, creation time, and optional TTL.

Runtime, session, and user records require the exact user. Project and audit records may be shared
only inside the exact tenant, project, and permission version. Every scope has distinct read and
write permissions. Candidate reads require an additional permission, expired/rejected records are
hidden, and classification cannot exceed the caller clearance. Audit records must be approved at
creation. Duplicate IDs fail instead of overwriting content.

The PostgreSQL `memory_record` table uses explicit tenant, project, user, and permission fields,
forced RLS, a scope/namespace/time index, and an update-denial trigger. Deletion remains reserved
for the governed S2-09 lifecycle path.
