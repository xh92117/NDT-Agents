"""Add immutable snapshots and restore decisions.

Revision ID: 0008_s2_restore
Revises: 0007_s2_memory
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0008_s2_restore"
down_revision = "0007_s2_memory"
branch_labels = None
depends_on = None

SNAPSHOT = "memory_snapshot"
EVENT = "memory_restore_event"


def upgrade() -> None:
    op.create_table(
        SNAPSHOT,
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("snapshot_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("permission_version", sa.String(128), nullable=False),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("branch_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("parent_snapshot_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("checkpoint_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("graph_version", sa.String(128), nullable=False),
        sa.Column("state_schema_version", sa.String(64), nullable=False),
        sa.Column("state", postgresql.JSONB(), nullable=False),
        sa.Column("state_sha256", sa.String(64), nullable=False),
        sa.Column("manifest", postgresql.JSONB(), nullable=False),
        sa.Column("injection_tokens", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "injection_tokens >= 1 AND injection_tokens <= 6000",
            name="ck_memory_snapshot_tokens",
        ),
        sa.PrimaryKeyConstraint(
            "tenant_id", "project_id", "snapshot_id", name="pk_memory_snapshot"
        ),
    )
    op.create_index(
        "ix_memory_snapshot_scope_task_created",
        SNAPSHOT,
        ["tenant_id", "project_id", "task_id", "created_at"],
    )
    op.create_table(
        EVENT,
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("decision_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("snapshot_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("permission_version", sa.String(128), nullable=False),
        sa.Column("preview_sha256", sa.String(64), nullable=False),
        sa.Column("outcome", sa.String(32), nullable=False),
        sa.Column("target_branch_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "outcome IN ('CONFIRMED','CANCELLED')", name="ck_memory_restore_event_outcome"
        ),
        sa.PrimaryKeyConstraint(
            "tenant_id", "project_id", "decision_id", name="pk_memory_restore_event"
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "project_id",
            "preview_sha256",
            name="uq_memory_restore_event_preview",
        ),
    )
    for table in (SNAPSHOT, EVENT):
        expression = (
            "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid AND "
            "project_id = NULLIF(current_setting('app.project_id', true), '')::uuid AND "
            "user_id = NULLIF(current_setting('app.user_id', true), '')::uuid AND "
            "permission_version = NULLIF(current_setting('app.permission_version', true), '')"
        )
        op.execute(sa.text(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY"))
        op.execute(sa.text(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY"))
        op.execute(
            sa.text(
                f"CREATE POLICY scope_isolation ON {table} "
                f"USING ({expression}) WITH CHECK ({expression})"
            )
        )
    op.execute(
        sa.text(
            "CREATE FUNCTION deny_restore_mutation() RETURNS trigger LANGUAGE plpgsql AS $$ "
            "BEGIN RAISE EXCEPTION 'snapshot and restore records are append-only'; END; $$"
        )
    )
    for table in (SNAPSHOT, EVENT):
        op.execute(
            sa.text(
                f"CREATE TRIGGER {table}_append_only BEFORE UPDATE OR DELETE ON {table} "
                "FOR EACH ROW EXECUTE FUNCTION deny_restore_mutation()"
            )
        )


def downgrade() -> None:
    for table in (EVENT, SNAPSHOT):
        op.execute(sa.text(f"DROP TRIGGER IF EXISTS {table}_append_only ON {table}"))
        op.execute(sa.text(f"DROP POLICY IF EXISTS scope_isolation ON {table}"))
        op.execute(sa.text(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY"))
        op.execute(sa.text(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY"))
    op.execute(sa.text("DROP FUNCTION IF EXISTS deny_restore_mutation()"))
    op.drop_table(EVENT)
    op.drop_index("ix_memory_snapshot_scope_task_created", table_name=SNAPSHOT)
    op.drop_table(SNAPSHOT)
