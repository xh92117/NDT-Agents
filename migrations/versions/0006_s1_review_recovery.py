"""Add immutable scoped review recovery event journal.

Revision ID: 0006_s1_review_recovery
Revises: 0005_s1_approval
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0006_s1_review_recovery"
down_revision = "0005_s1_approval"
branch_labels = None
depends_on = None

TABLE = "runtime_review_recovery_event"


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("recovery_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sequence", sa.BigInteger(), nullable=False),
        sa.Column("event_type", sa.String(32), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("payload_sha256", sa.String(64), nullable=False),
        sa.Column("previous_sha256", sa.String(64), nullable=False),
        sa.Column("event_sha256", sa.String(64), nullable=False),
        sa.CheckConstraint("sequence >= 1", name="ck_review_recovery_sequence_positive"),
        sa.CheckConstraint(
            "event_type IN ('PREPARED','REVIEW_OUTPUT','CORRECTION_OUTPUT','RESULT')",
            name="ck_review_recovery_event_type",
        ),
        sa.PrimaryKeyConstraint(
            "tenant_id", "project_id", "event_id", name="pk_review_recovery_event"
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "project_id",
            "recovery_id",
            "sequence",
            name="uq_review_recovery_sequence",
        ),
    )
    expression = (
        "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid AND "
        "project_id = NULLIF(current_setting('app.project_id', true), '')::uuid"
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
            "CREATE FUNCTION deny_review_recovery_mutation() RETURNS trigger "
            "LANGUAGE plpgsql AS $$ BEGIN "
            "RAISE EXCEPTION 'review recovery events are append-only'; END; $$"
        )
    )
    op.execute(
        sa.text(
            f"CREATE TRIGGER review_recovery_append_only BEFORE UPDATE OR DELETE ON {TABLE} "
            "FOR EACH ROW EXECUTE FUNCTION deny_review_recovery_mutation()"
        )
    )


def downgrade() -> None:
    op.execute(sa.text(f"DROP TRIGGER IF EXISTS review_recovery_append_only ON {TABLE}"))
    op.execute(sa.text("DROP FUNCTION IF EXISTS deny_review_recovery_mutation()"))
    op.execute(sa.text(f"DROP POLICY IF EXISTS scope_isolation ON {TABLE}"))
    op.execute(sa.text(f"ALTER TABLE {TABLE} NO FORCE ROW LEVEL SECURITY"))
    op.execute(sa.text(f"ALTER TABLE {TABLE} DISABLE ROW LEVEL SECURITY"))
    op.drop_table(TABLE)
