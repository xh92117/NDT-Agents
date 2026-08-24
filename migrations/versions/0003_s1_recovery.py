"""Add scoped recovery output, side-effect, and interrupt journals.

Revision ID: 0003_s1_recovery
Revises: 0002_s1_identity_rls
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0003_s1_recovery"
down_revision = "0002_s1_identity_rls"
branch_labels = None
depends_on = None

RECOVERY_TABLES = (
    "runtime_assignment_output",
    "runtime_side_effect",
    "runtime_interrupt",
)


def _project_expression() -> str:
    return (
        "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid AND "
        "project_id = NULLIF(current_setting('app.project_id', true), '')::uuid"
    )


def _enable_policy(table: str) -> None:
    expression = _project_expression()
    op.execute(sa.text(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY"))
    op.execute(sa.text(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY"))
    op.execute(
        sa.text(
            f"CREATE POLICY scope_isolation ON {table} "
            f"USING ({expression}) WITH CHECK ({expression})"
        )
    )


def _disable_policy(table: str) -> None:
    op.execute(sa.text(f"DROP POLICY IF EXISTS scope_isolation ON {table}"))
    op.execute(sa.text(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY"))
    op.execute(sa.text(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY"))


def _scope_columns() -> tuple[sa.Column[object], sa.Column[object], sa.Column[object]]:
    return (
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("recovery_id", postgresql.UUID(as_uuid=True), nullable=False),
    )


def upgrade() -> None:
    op.add_column(
        "runtime_checkpoint",
        sa.Column(
            "graph_version",
            sa.String(128),
            server_default="scheduler-recovery-1",
            nullable=False,
        ),
    )
    op.create_table(
        "runtime_assignment_output",
        *_scope_columns(),
        sa.Column("assignment_id", sa.String(128), nullable=False),
        sa.Column("context_manifest_sha256", sa.String(64), nullable=False),
        sa.Column("output_sha256", sa.String(64), nullable=False),
        sa.Column("output", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint(
            "tenant_id",
            "project_id",
            "recovery_id",
            "assignment_id",
            name="pk_runtime_assignment_output",
        ),
    )
    op.create_table(
        "runtime_side_effect",
        *_scope_columns(),
        sa.Column("side_effect_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_sha256", sa.String(64), nullable=False),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("output_sha256", sa.String(64), nullable=True),
        sa.Column("output", postgresql.JSONB(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "state IN ('STARTED','COMMITTED')",
            name="ck_runtime_side_effect_state",
        ),
        sa.PrimaryKeyConstraint(
            "tenant_id",
            "project_id",
            "recovery_id",
            "side_effect_id",
            name="pk_runtime_side_effect",
        ),
    )
    op.create_table(
        "runtime_interrupt",
        *_scope_columns(),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("reason", sa.String(1000), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "state IN ('REQUESTED','CLEARED')",
            name="ck_runtime_interrupt_state",
        ),
        sa.PrimaryKeyConstraint(
            "tenant_id",
            "project_id",
            "recovery_id",
            name="pk_runtime_interrupt",
        ),
    )
    for table in RECOVERY_TABLES:
        _enable_policy(table)


def downgrade() -> None:
    for table in reversed(RECOVERY_TABLES):
        _disable_policy(table)
        op.drop_table(table)
    op.drop_column("runtime_checkpoint", "graph_version")
