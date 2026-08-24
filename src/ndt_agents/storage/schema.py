"""S1 PostgreSQL and pgvector schema metadata with explicit project scope."""

from __future__ import annotations

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects.postgresql import JSONB, UUID

metadata = sa.MetaData(
    naming_convention={
        "ix": "ix_%(table_name)s_%(column_0_N_name)s",
        "uq": "uq_%(table_name)s_%(column_0_N_name)s",
        "ck": "ck_%(table_name)s_%(constraint_name)s",
        "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
        "pk": "pk_%(table_name)s",
    }
)

tenant_registry = sa.Table(
    "tenant_registry",
    metadata,
    sa.Column("tenant_id", UUID(as_uuid=True), primary_key=True),
    sa.Column("display_name", sa.String(256), nullable=False),
    sa.Column("status", sa.String(32), nullable=False),
    sa.Column(
        "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    ),
    sa.CheckConstraint("status IN ('ACTIVE','SUSPENDED','DISABLED')", name="status"),
)

project_registry = sa.Table(
    "project_registry",
    metadata,
    sa.Column("tenant_id", UUID(as_uuid=True), primary_key=True),
    sa.Column("project_id", UUID(as_uuid=True), primary_key=True),
    sa.Column("display_name", sa.String(256), nullable=False),
    sa.Column("status", sa.String(32), nullable=False),
    sa.Column(
        "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    ),
    sa.CheckConstraint("status IN ('ACTIVE','SUSPENDED','CLOSED')", name="status"),
)

tenant_membership = sa.Table(
    "tenant_membership",
    metadata,
    sa.Column("tenant_id", UUID(as_uuid=True), primary_key=True),
    sa.Column("user_id", UUID(as_uuid=True), primary_key=True),
    sa.Column("oidc_subject", sa.String(512), nullable=False),
    sa.Column("role_codes", JSONB(), nullable=False),
    sa.Column("permission_version", sa.String(128), nullable=False),
    sa.Column("status", sa.String(32), nullable=False),
    sa.Column(
        "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    ),
    sa.CheckConstraint("status IN ('ACTIVE','SUSPENDED','REVOKED')", name="status"),
    sa.UniqueConstraint("tenant_id", "oidc_subject"),
)

project_membership = sa.Table(
    "project_membership",
    metadata,
    sa.Column("tenant_id", UUID(as_uuid=True), primary_key=True),
    sa.Column("project_id", UUID(as_uuid=True), primary_key=True),
    sa.Column("user_id", UUID(as_uuid=True), primary_key=True),
    sa.Column("role_codes", JSONB(), nullable=False),
    sa.Column("permission_version", sa.String(128), nullable=False),
    sa.Column("status", sa.String(32), nullable=False),
    sa.Column(
        "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    ),
    sa.CheckConstraint("status IN ('ACTIVE','SUSPENDED','REVOKED')", name="status"),
)

runtime_task = sa.Table(
    "runtime_task",
    metadata,
    sa.Column("tenant_id", UUID(as_uuid=True), primary_key=True),
    sa.Column("project_id", UUID(as_uuid=True), primary_key=True),
    sa.Column("task_id", UUID(as_uuid=True), primary_key=True),
    sa.Column("task_class", sa.String(8), nullable=False),
    sa.Column("state", sa.String(32), nullable=False),
    sa.Column("state_version", sa.Integer(), nullable=False, server_default="1"),
    sa.Column("idempotency_key", sa.String(256), nullable=False),
    sa.Column("payload", JSONB(), nullable=False),
    sa.Column(
        "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    ),
    sa.Column(
        "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    ),
    sa.CheckConstraint(
        "state IN ('CREATED','RUNNING','WAITING','COMPLETED','FAILED','BLOCKED','CANCELLED')",
        name="state",
    ),
    sa.UniqueConstraint("tenant_id", "project_id", "idempotency_key"),
)

runtime_checkpoint = sa.Table(
    "runtime_checkpoint",
    metadata,
    sa.Column("tenant_id", UUID(as_uuid=True), primary_key=True),
    sa.Column("project_id", UUID(as_uuid=True), primary_key=True),
    sa.Column("checkpoint_id", UUID(as_uuid=True), primary_key=True),
    sa.Column("task_id", UUID(as_uuid=True), nullable=False),
    sa.Column("sequence", sa.Integer(), nullable=False),
    sa.Column(
        "graph_version",
        sa.String(128),
        nullable=False,
        server_default="scheduler-recovery-1",
    ),
    sa.Column("state_schema_version", sa.String(64), nullable=False),
    sa.Column("state_artifact_id", UUID(as_uuid=True), nullable=False),
    sa.Column("state_sha256", sa.String(64), nullable=False),
    sa.Column("committed_side_effect_ids", JSONB(), nullable=False),
    sa.Column(
        "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    ),
    sa.CheckConstraint("sequence >= 0", name="sequence_nonnegative"),
    sa.UniqueConstraint("tenant_id", "project_id", "task_id", "sequence"),
)

runtime_assignment_output = sa.Table(
    "runtime_assignment_output",
    metadata,
    sa.Column("tenant_id", UUID(as_uuid=True), primary_key=True),
    sa.Column("project_id", UUID(as_uuid=True), primary_key=True),
    sa.Column("recovery_id", UUID(as_uuid=True), primary_key=True),
    sa.Column("assignment_id", sa.String(128), primary_key=True),
    sa.Column("context_manifest_sha256", sa.String(64), nullable=False),
    sa.Column("output_sha256", sa.String(64), nullable=False),
    sa.Column("output", JSONB(), nullable=False),
    sa.Column(
        "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    ),
)

runtime_side_effect = sa.Table(
    "runtime_side_effect",
    metadata,
    sa.Column("tenant_id", UUID(as_uuid=True), primary_key=True),
    sa.Column("project_id", UUID(as_uuid=True), primary_key=True),
    sa.Column("recovery_id", UUID(as_uuid=True), primary_key=True),
    sa.Column("side_effect_id", UUID(as_uuid=True), primary_key=True),
    sa.Column("request_sha256", sa.String(64), nullable=False),
    sa.Column("state", sa.String(32), nullable=False),
    sa.Column("output_sha256", sa.String(64), nullable=True),
    sa.Column("output", JSONB(), nullable=True),
    sa.Column(
        "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    ),
    sa.Column(
        "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    ),
    sa.CheckConstraint("state IN ('STARTED','COMMITTED')", name="state"),
)

runtime_interrupt = sa.Table(
    "runtime_interrupt",
    metadata,
    sa.Column("tenant_id", UUID(as_uuid=True), primary_key=True),
    sa.Column("project_id", UUID(as_uuid=True), primary_key=True),
    sa.Column("recovery_id", UUID(as_uuid=True), primary_key=True),
    sa.Column("task_id", UUID(as_uuid=True), nullable=False),
    sa.Column("state", sa.String(32), nullable=False),
    sa.Column("reason", sa.String(1000), nullable=False),
    sa.Column(
        "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    ),
    sa.CheckConstraint("state IN ('REQUESTED','CLEARED')", name="state"),
)

runtime_audit_event = sa.Table(
    "runtime_audit_event",
    metadata,
    sa.Column("tenant_id", UUID(as_uuid=True), primary_key=True),
    sa.Column("project_id", UUID(as_uuid=True), primary_key=True),
    sa.Column("event_id", UUID(as_uuid=True), primary_key=True),
    sa.Column("sequence", sa.BigInteger(), nullable=False),
    sa.Column("actor_user_id", UUID(as_uuid=True), nullable=False),
    sa.Column("role_codes", JSONB(), nullable=False),
    sa.Column("permission_version", sa.String(128), nullable=False),
    sa.Column("kind", sa.String(32), nullable=False),
    sa.Column("action", sa.String(128), nullable=False),
    sa.Column("target_type", sa.String(64), nullable=False),
    sa.Column("target_id", sa.String(256), nullable=False),
    sa.Column("task_id", UUID(as_uuid=True), nullable=True),
    sa.Column("policy_version", sa.String(128), nullable=False),
    sa.Column("decision", sa.String(64), nullable=False),
    sa.Column("outcome", sa.String(32), nullable=False),
    sa.Column("input_sha256", sa.String(64), nullable=False),
    sa.Column("output_sha256", sa.String(64), nullable=False),
    sa.Column("request_id", sa.String(128), nullable=False),
    sa.Column("trace_id", sa.String(32), nullable=False),
    sa.Column("span_id", sa.String(16), nullable=False),
    sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("previous_sha256", sa.String(64), nullable=False),
    sa.Column("event_sha256", sa.String(64), nullable=False),
    sa.Column(
        "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    ),
    sa.CheckConstraint("sequence >= 1", name="sequence_positive"),
    sa.CheckConstraint("outcome IN ('SUCCESS','PARTIAL','DENIED','FAILED')", name="outcome"),
    sa.UniqueConstraint("tenant_id", "project_id", "sequence"),
    sa.UniqueConstraint("tenant_id", "project_id", "event_sha256"),
)

memory_record = sa.Table(
    "memory_record",
    metadata,
    sa.Column("tenant_id", UUID(as_uuid=True), primary_key=True),
    sa.Column("project_id", UUID(as_uuid=True), primary_key=True),
    sa.Column("memory_id", UUID(as_uuid=True), primary_key=True),
    sa.Column("user_id", UUID(as_uuid=True), nullable=False),
    sa.Column("permission_version", sa.String(128), nullable=False),
    sa.Column("memory_scope", sa.String(32), nullable=False),
    sa.Column("namespace_id", sa.String(128), nullable=False),
    sa.Column("content", JSONB(), nullable=False),
    sa.Column("content_sha256", sa.String(64), nullable=False),
    sa.Column("provenance_ids", JSONB(), nullable=False),
    sa.Column("confidence", sa.Float(), nullable=False),
    sa.Column("classification", sa.String(32), nullable=False),
    sa.Column("approval_state", sa.String(32), nullable=False),
    sa.Column("protected", sa.Boolean(), nullable=False, server_default=sa.false()),
    sa.Column("source_version", sa.String(128), nullable=False),
    sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint(
        "memory_scope IN ('RUNTIME','SESSION','USER','PROJECT','AUDIT')",
        name="scope",
    ),
    sa.CheckConstraint(
        "approval_state IN ('CANDIDATE','APPROVED','REJECTED','EXPIRED')",
        name="approval_state",
    ),
    sa.CheckConstraint("confidence >= 0 AND confidence <= 1", name="confidence"),
    sa.Index(
        "ix_memory_record_scope_namespace_created",
        "tenant_id",
        "project_id",
        "memory_scope",
        "namespace_id",
        "created_at",
    ),
)

memory_snapshot = sa.Table(
    "memory_snapshot",
    metadata,
    sa.Column("tenant_id", UUID(as_uuid=True), primary_key=True),
    sa.Column("project_id", UUID(as_uuid=True), primary_key=True),
    sa.Column("snapshot_id", UUID(as_uuid=True), primary_key=True),
    sa.Column("user_id", UUID(as_uuid=True), nullable=False),
    sa.Column("permission_version", sa.String(128), nullable=False),
    sa.Column("task_id", UUID(as_uuid=True), nullable=False),
    sa.Column("branch_id", UUID(as_uuid=True), nullable=False),
    sa.Column("parent_snapshot_id", UUID(as_uuid=True), nullable=True),
    sa.Column("checkpoint_id", UUID(as_uuid=True), nullable=False),
    sa.Column("graph_version", sa.String(128), nullable=False),
    sa.Column("state_schema_version", sa.String(64), nullable=False),
    sa.Column("state", JSONB(), nullable=False),
    sa.Column("state_sha256", sa.String(64), nullable=False),
    sa.Column("manifest", JSONB(), nullable=False),
    sa.Column("injection_tokens", sa.Integer(), nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("injection_tokens >= 1 AND injection_tokens <= 6000", name="tokens"),
    sa.Index(
        "ix_memory_snapshot_scope_task_created", "tenant_id", "project_id", "task_id", "created_at"
    ),
)

memory_restore_event = sa.Table(
    "memory_restore_event",
    metadata,
    sa.Column("tenant_id", UUID(as_uuid=True), primary_key=True),
    sa.Column("project_id", UUID(as_uuid=True), primary_key=True),
    sa.Column("decision_id", UUID(as_uuid=True), primary_key=True),
    sa.Column("snapshot_id", UUID(as_uuid=True), nullable=False),
    sa.Column("user_id", UUID(as_uuid=True), nullable=False),
    sa.Column("permission_version", sa.String(128), nullable=False),
    sa.Column("preview_sha256", sa.String(64), nullable=False),
    sa.Column("outcome", sa.String(32), nullable=False),
    sa.Column("target_branch_id", UUID(as_uuid=True), nullable=True),
    sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("outcome IN ('CONFIRMED','CANCELLED')", name="outcome"),
    sa.UniqueConstraint("tenant_id", "project_id", "preview_sha256"),
)

cache_entry = sa.Table(
    "cache_entry",
    metadata,
    sa.Column("tenant_id", UUID(as_uuid=True), primary_key=True),
    sa.Column("project_id", UUID(as_uuid=True), primary_key=True),
    sa.Column("user_id", UUID(as_uuid=True), primary_key=True),
    sa.Column("permission_version", sa.String(128), primary_key=True),
    sa.Column("cache_class", sa.String(32), primary_key=True),
    sa.Column("cache_key_sha256", sa.String(64), primary_key=True),
    sa.Column("cache_entry_id", UUID(as_uuid=True), nullable=False),
    sa.Column("value", JSONB(), nullable=False),
    sa.Column("value_sha256", sa.String(64), nullable=False),
    sa.Column("version_manifest", JSONB(), nullable=False),
    sa.Column("provenance", JSONB(), nullable=False),
    sa.Column("validation_state", sa.String(32), nullable=False),
    sa.Column("saved_tokens", sa.Integer(), nullable=False, server_default="0"),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint(
        "cache_class IN ('EXACT','RETRIEVAL','TOOL','PARSE','SEMANTIC')",
        name="class",
    ),
    sa.CheckConstraint("validation_state IN ('VALID','STALE','REJECTED')", name="state"),
    sa.Index("ix_cache_entry_expiry", "tenant_id", "project_id", "expires_at"),
)

data_lifecycle_object = sa.Table(
    "data_lifecycle_object",
    metadata,
    sa.Column("tenant_id", UUID(as_uuid=True), primary_key=True),
    sa.Column("project_id", UUID(as_uuid=True), primary_key=True),
    sa.Column("object_id", UUID(as_uuid=True), primary_key=True),
    sa.Column("user_id", UUID(as_uuid=True), nullable=False),
    sa.Column("permission_version", sa.String(128), nullable=False),
    sa.Column("object_type", sa.String(128), nullable=False),
    sa.Column("object_version", sa.String(128), nullable=False),
    sa.Column("classification", sa.String(32), nullable=False),
    sa.Column("content", JSONB(), nullable=True),
    sa.Column("content_sha256", sa.String(64), nullable=False),
    sa.Column("retention_until", sa.DateTime(timezone=True), nullable=False),
    sa.Column("encryption_key_ref", JSONB(), nullable=True),
    sa.Column("state", sa.String(32), nullable=False),
    sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("crypto_erased_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("state IN ('ACTIVE','DELETED','CRYPTO_ERASED')", name="state"),
    sa.Index("ix_data_lifecycle_retention", "tenant_id", "project_id", "state", "retention_until"),
)

data_legal_hold = sa.Table(
    "data_legal_hold",
    metadata,
    sa.Column("tenant_id", UUID(as_uuid=True), primary_key=True),
    sa.Column("project_id", UUID(as_uuid=True), primary_key=True),
    sa.Column("hold_id", UUID(as_uuid=True), primary_key=True),
    sa.Column("user_id", UUID(as_uuid=True), nullable=False),
    sa.Column("permission_version", sa.String(128), nullable=False),
    sa.Column("object_id", UUID(as_uuid=True), nullable=False),
    sa.Column("reason", sa.String(2000), nullable=False),
    sa.Column("state", sa.String(32), nullable=False),
    sa.Column("approval_id", UUID(as_uuid=True), nullable=False),
    sa.Column("applied_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint("state IN ('ACTIVE','RELEASED')", name="state"),
)

data_lifecycle_event = sa.Table(
    "data_lifecycle_event",
    metadata,
    sa.Column("tenant_id", UUID(as_uuid=True), primary_key=True),
    sa.Column("project_id", UUID(as_uuid=True), primary_key=True),
    sa.Column("event_id", UUID(as_uuid=True), primary_key=True),
    sa.Column("user_id", UUID(as_uuid=True), nullable=False),
    sa.Column("permission_version", sa.String(128), nullable=False),
    sa.Column("action", sa.String(32), nullable=False),
    sa.Column("object_ids", JSONB(), nullable=False),
    sa.Column("input_sha256", sa.String(64), nullable=False),
    sa.Column("outcome_sha256", sa.String(64), nullable=False),
    sa.Column("approval_id", UUID(as_uuid=True), nullable=True),
    sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
)

artifact_record = sa.Table(
    "artifact_record",
    metadata,
    sa.Column("tenant_id", UUID(as_uuid=True), primary_key=True),
    sa.Column("project_id", UUID(as_uuid=True), primary_key=True),
    sa.Column("artifact_id", UUID(as_uuid=True), primary_key=True),
    sa.Column("artifact_version", sa.String(64), primary_key=True),
    sa.Column("object_key", sa.String(1024), nullable=False),
    sa.Column("media_type", sa.String(255), nullable=False),
    sa.Column("size_bytes", sa.BigInteger(), nullable=False),
    sa.Column("sha256", sa.String(64), nullable=False),
    sa.Column("classification", sa.String(32), nullable=False),
    sa.Column("immutable", sa.Boolean(), nullable=False, server_default=sa.true()),
    sa.Column(
        "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    ),
    sa.CheckConstraint("size_bytes >= 0", name="size_nonnegative"),
    sa.UniqueConstraint("tenant_id", "project_id", "object_key"),
)

knowledge_embedding = sa.Table(
    "knowledge_embedding",
    metadata,
    sa.Column("tenant_id", UUID(as_uuid=True), primary_key=True),
    sa.Column("project_id", UUID(as_uuid=True), primary_key=True),
    sa.Column("embedding_id", UUID(as_uuid=True), primary_key=True),
    sa.Column("source_artifact_id", UUID(as_uuid=True), nullable=False),
    sa.Column("source_version", sa.String(64), nullable=False),
    sa.Column("chunk_id", sa.String(128), nullable=False),
    sa.Column("embedding", Vector(1536), nullable=False),
    sa.Column("metadata", JSONB(), nullable=False),
    sa.Column(
        "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    ),
    sa.UniqueConstraint("tenant_id", "project_id", "source_artifact_id", "chunk_id"),
)
