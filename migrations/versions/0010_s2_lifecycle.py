"""Add governed S2 data-lifecycle records.

Revision ID: 0010_s2_lifecycle
Revises: 0009_s2_cache
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0010_s2_lifecycle"
down_revision = "0009_s2_cache"
branch_labels = None
depends_on = None

OBJECT = "data_lifecycle_object"
HOLD = "data_legal_hold"
EVENT = "data_lifecycle_event"


def upgrade() -> None:
    op.create_table(
        OBJECT,
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("object_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("permission_version", sa.String(128), nullable=False),
        sa.Column("object_type", sa.String(128), nullable=False),
        sa.Column("object_version", sa.String(128), nullable=False),
        sa.Column("classification", sa.String(32), nullable=False),
        sa.Column("content", postgresql.JSONB(), nullable=True),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("retention_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("encryption_key_ref", postgresql.JSONB(), nullable=True),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("crypto_erased_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "state IN ('ACTIVE','DELETED','CRYPTO_ERASED')",
            name="ck_data_lifecycle_object_state",
        ),
        sa.PrimaryKeyConstraint(
            "tenant_id", "project_id", "object_id", name="pk_data_lifecycle_object"
        ),
    )
    op.create_index(
        "ix_data_lifecycle_retention",
        OBJECT,
        ["tenant_id", "project_id", "state", "retention_until"],
    )
    op.create_table(
        HOLD,
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("hold_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("permission_version", sa.String(128), nullable=False),
        sa.Column("object_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("reason", sa.String(2000), nullable=False),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("approval_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("state IN ('ACTIVE','RELEASED')", name="ck_data_legal_hold_state"),
        sa.PrimaryKeyConstraint("tenant_id", "project_id", "hold_id", name="pk_data_legal_hold"),
    )
    op.create_table(
        EVENT,
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("permission_version", sa.String(128), nullable=False),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("object_ids", postgresql.JSONB(), nullable=False),
        sa.Column("input_sha256", sa.String(64), nullable=False),
        sa.Column("outcome_sha256", sa.String(64), nullable=False),
        sa.Column("approval_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint(
            "tenant_id", "project_id", "event_id", name="pk_data_lifecycle_event"
        ),
    )
    expression = (
        "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid AND "
        "project_id = NULLIF(current_setting('app.project_id', true), '')::uuid AND "
        "user_id = NULLIF(current_setting('app.user_id', true), '')::uuid AND "
        "permission_version = NULLIF(current_setting('app.permission_version', true), '')"
    )
    for table in (OBJECT, HOLD, EVENT):
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
            "CREATE FUNCTION deny_lifecycle_event_mutation() RETURNS trigger "
            "LANGUAGE plpgsql AS $$ BEGIN "
            "RAISE EXCEPTION 'lifecycle events are append-only'; END; $$"
        )
    )
    op.execute(
        sa.text(
            f"CREATE TRIGGER lifecycle_event_append_only BEFORE UPDATE OR DELETE ON {EVENT} "
            "FOR EACH ROW EXECUTE FUNCTION deny_lifecycle_event_mutation()"
        )
    )


def downgrade() -> None:
    op.execute(sa.text(f"DROP TRIGGER IF EXISTS lifecycle_event_append_only ON {EVENT}"))
    op.execute(sa.text("DROP FUNCTION IF EXISTS deny_lifecycle_event_mutation()"))
    for table in (EVENT, HOLD, OBJECT):
        op.execute(sa.text(f"DROP POLICY IF EXISTS scope_isolation ON {table}"))
        op.execute(sa.text(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY"))
        op.execute(sa.text(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY"))
    op.drop_table(EVENT)
    op.drop_table(HOLD)
    op.drop_index("ix_data_lifecycle_retention", table_name=OBJECT)
    op.drop_table(OBJECT)
