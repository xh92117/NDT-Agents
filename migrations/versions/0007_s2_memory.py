"""Add scoped immutable S2 memory records.

Revision ID: 0007_s2_memory
Revises: 0006_s1_review_recovery
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0007_s2_memory"
down_revision = "0006_s1_review_recovery"
branch_labels = None
depends_on = None

TABLE = "memory_record"


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("memory_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("permission_version", sa.String(128), nullable=False),
        sa.Column("memory_scope", sa.String(32), nullable=False),
        sa.Column("namespace_id", sa.String(128), nullable=False),
        sa.Column("content", postgresql.JSONB(), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("provenance_ids", postgresql.JSONB(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("classification", sa.String(32), nullable=False),
        sa.Column("approval_state", sa.String(32), nullable=False),
        sa.Column("protected", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("source_version", sa.String(128), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "memory_scope IN ('RUNTIME','SESSION','USER','PROJECT','AUDIT')",
            name="ck_memory_record_scope",
        ),
        sa.CheckConstraint(
            "approval_state IN ('CANDIDATE','APPROVED','REJECTED','EXPIRED')",
            name="ck_memory_record_approval_state",
        ),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1", name="ck_memory_record_confidence"
        ),
        sa.PrimaryKeyConstraint("tenant_id", "project_id", "memory_id", name="pk_memory_record"),
    )
    op.create_index(
        "ix_memory_record_scope_namespace_created",
        TABLE,
        ["tenant_id", "project_id", "memory_scope", "namespace_id", "created_at"],
    )
    expression = (
        "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid AND "
        "project_id = NULLIF(current_setting('app.project_id', true), '')::uuid AND "
        "permission_version = NULLIF(current_setting('app.permission_version', true), '') AND "
        "(memory_scope IN ('PROJECT','AUDIT') OR "
        "user_id = NULLIF(current_setting('app.user_id', true), '')::uuid)"
    )
    op.execute(sa.text(f"ALTER TABLE {TABLE} ENABLE ROW LEVEL SECURITY"))
    op.execute(sa.text(f"ALTER TABLE {TABLE} FORCE ROW LEVEL SECURITY"))
    op.execute(
        sa.text(
            f"CREATE POLICY scope_isolation ON {TABLE} "
            f"USING ({expression}) WITH CHECK ({expression})"
        )
    )
    op.execute(
        sa.text(
            "CREATE FUNCTION deny_memory_update() RETURNS trigger LANGUAGE plpgsql AS $$ "
            "BEGIN RAISE EXCEPTION 'memory records are immutable'; END; $$"
        )
    )
    op.execute(
        sa.text(
            f"CREATE TRIGGER memory_record_no_update BEFORE UPDATE ON {TABLE} "
            "FOR EACH ROW EXECUTE FUNCTION deny_memory_update()"
        )
    )


def downgrade() -> None:
    op.execute(sa.text(f"DROP TRIGGER IF EXISTS memory_record_no_update ON {TABLE}"))
    op.execute(sa.text("DROP FUNCTION IF EXISTS deny_memory_update()"))
    op.execute(sa.text(f"DROP POLICY IF EXISTS scope_isolation ON {TABLE}"))
    op.execute(sa.text(f"ALTER TABLE {TABLE} NO FORCE ROW LEVEL SECURITY"))
    op.execute(sa.text(f"ALTER TABLE {TABLE} DISABLE ROW LEVEL SECURITY"))
    op.drop_index("ix_memory_record_scope_namespace_created", table_name=TABLE)
    op.drop_table(TABLE)
