"""Create the scoped S1 storage foundation.

Revision ID: 0001_s1_storage
Revises: none
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision = "0001_s1_storage"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector"))
    op.create_table(
        "runtime_task",
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("task_class", sa.String(8), nullable=False),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("state_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("idempotency_key", sa.String(256), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "state IN ('CREATED','RUNNING','WAITING','COMPLETED','FAILED','BLOCKED','CANCELLED')",
            name="ck_runtime_task_state",
        ),
        sa.PrimaryKeyConstraint("tenant_id", "project_id", "task_id", name="pk_runtime_task"),
        sa.UniqueConstraint(
            "tenant_id",
            "project_id",
            "idempotency_key",
            name="uq_runtime_task_tenant_id_project_id_idempotency_key",
        ),
    )
    op.create_table(
        "runtime_checkpoint",
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("checkpoint_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("state_schema_version", sa.String(64), nullable=False),
        sa.Column("state_artifact_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("state_sha256", sa.String(64), nullable=False),
        sa.Column("committed_side_effect_ids", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("sequence >= 0", name="ck_runtime_checkpoint_sequence_nonnegative"),
        sa.PrimaryKeyConstraint(
            "tenant_id", "project_id", "checkpoint_id", name="pk_runtime_checkpoint"
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "project_id",
            "task_id",
            "sequence",
            name="uq_runtime_checkpoint_tenant_id_project_id_task_id_sequence",
        ),
    )
    op.create_table(
        "artifact_record",
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("artifact_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("artifact_version", sa.String(64), nullable=False),
        sa.Column("object_key", sa.String(1024), nullable=False),
        sa.Column("media_type", sa.String(255), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("classification", sa.String(32), nullable=False),
        sa.Column("immutable", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("size_bytes >= 0", name="ck_artifact_record_size_nonnegative"),
        sa.PrimaryKeyConstraint(
            "tenant_id",
            "project_id",
            "artifact_id",
            "artifact_version",
            name="pk_artifact_record",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "project_id",
            "object_key",
            name="uq_artifact_record_tenant_id_project_id_object_key",
        ),
    )
    op.create_table(
        "knowledge_embedding",
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("embedding_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_artifact_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_version", sa.String(64), nullable=False),
        sa.Column("chunk_id", sa.String(128), nullable=False),
        sa.Column("embedding", Vector(1536), nullable=False),
        sa.Column("metadata", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint(
            "tenant_id", "project_id", "embedding_id", name="pk_knowledge_embedding"
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "project_id",
            "source_artifact_id",
            "chunk_id",
            name="uq_ke_scope_source_chunk",
        ),
    )


def downgrade() -> None:
    op.drop_table("knowledge_embedding")
    op.drop_table("artifact_record")
    op.drop_table("runtime_checkpoint")
    op.drop_table("runtime_task")
