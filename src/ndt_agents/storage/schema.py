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
