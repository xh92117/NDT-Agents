"""Add immutable scoped approval event journal.

Revision ID: 0005_s1_approval
Revises: 0004_s1_audit
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0005_s1_approval"
down_revision = "0004_s1_audit"
branch_labels = None
depends_on = None

TABLE = "runtime_approval_event"


def _project_expression() -> str:
    return (
        "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid AND "
        "project_id = NULLIF(current_setting('app.project_id', true), '')::uuid"
    )


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("approval_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sequence", sa.BigInteger(), nullable=False),
        sa.Column("event_type", sa.String(32), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("payload_sha256", sa.String(64), nullable=False),
        sa.Column("previous_sha256", sa.String(64), nullable=False),
        sa.Column("event_sha256", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("sequence >= 1", name="ck_runtime_approval_event_sequence_positive"),
        sa.CheckConstraint(
            "event_type IN ('CANDIDATE','DELEGATION','DECISION','RESUME')",
            name="ck_runtime_approval_event_type",
        ),
        sa.PrimaryKeyConstraint(
            "tenant_id", "project_id", "event_id", name="pk_runtime_approval_event"
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "project_id",
            "approval_id",
            "sequence",
            name="uq_runtime_approval_event_sequence",
        ),
    )
    expression = _project_expression()
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
            "CREATE FUNCTION deny_runtime_approval_event_mutation() RETURNS trigger "
            "LANGUAGE plpgsql AS $$ BEGIN "
            "RAISE EXCEPTION 'runtime approval events are append-only'; END; $$"
        )
    )
    op.execute(
        sa.text(
            f"CREATE TRIGGER runtime_approval_event_append_only BEFORE UPDATE OR DELETE ON {TABLE} "
            "FOR EACH ROW EXECUTE FUNCTION deny_runtime_approval_event_mutation()"
        )
    )


def downgrade() -> None:
    op.execute(sa.text(f"DROP TRIGGER IF EXISTS runtime_approval_event_append_only ON {TABLE}"))
    op.execute(sa.text("DROP FUNCTION IF EXISTS deny_runtime_approval_event_mutation()"))
    op.execute(sa.text(f"DROP POLICY IF EXISTS scope_isolation ON {TABLE}"))
    op.execute(sa.text(f"ALTER TABLE {TABLE} NO FORCE ROW LEVEL SECURITY"))
    op.execute(sa.text(f"ALTER TABLE {TABLE} DISABLE ROW LEVEL SECURITY"))
    op.drop_table(TABLE)
