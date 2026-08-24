"""Add immutable scoped runtime audit events.

Revision ID: 0004_s1_audit
Revises: 0003_s1_recovery
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0004_s1_audit"
down_revision = "0003_s1_recovery"
branch_labels = None
depends_on = None

TABLE = "runtime_audit_event"


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
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sequence", sa.BigInteger(), nullable=False),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role_codes", postgresql.JSONB(), nullable=False),
        sa.Column("permission_version", sa.String(128), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("action", sa.String(128), nullable=False),
        sa.Column("target_type", sa.String(64), nullable=False),
        sa.Column("target_id", sa.String(256), nullable=False),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=True),
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
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("sequence >= 1", name="ck_runtime_audit_event_sequence_positive"),
        sa.CheckConstraint(
            "outcome IN ('SUCCESS','PARTIAL','DENIED','FAILED')",
            name="ck_runtime_audit_event_outcome",
        ),
        sa.PrimaryKeyConstraint(
            "tenant_id", "project_id", "event_id", name="pk_runtime_audit_event"
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "project_id",
            "sequence",
            name="uq_runtime_audit_event_tenant_project_sequence",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "project_id",
            "event_sha256",
            name="uq_runtime_audit_event_tenant_project_event_sha256",
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
            "CREATE FUNCTION deny_runtime_audit_event_mutation() RETURNS trigger "
            "LANGUAGE plpgsql AS $$ BEGIN "
            "RAISE EXCEPTION 'runtime audit events are append-only'; END; $$"
        )
    )
    op.execute(
        sa.text(
            f"CREATE TRIGGER runtime_audit_event_append_only BEFORE UPDATE OR DELETE ON {TABLE} "
            "FOR EACH ROW EXECUTE FUNCTION deny_runtime_audit_event_mutation()"
        )
    )


def downgrade() -> None:
    op.execute(sa.text(f"DROP TRIGGER IF EXISTS runtime_audit_event_append_only ON {TABLE}"))
    op.execute(sa.text("DROP FUNCTION IF EXISTS deny_runtime_audit_event_mutation()"))
    op.execute(sa.text(f"DROP POLICY IF EXISTS scope_isolation ON {TABLE}"))
    op.execute(sa.text(f"ALTER TABLE {TABLE} NO FORCE ROW LEVEL SECURITY"))
    op.execute(sa.text(f"ALTER TABLE {TABLE} DISABLE ROW LEVEL SECURITY"))
    op.drop_table(TABLE)
