"""Create identity memberships and force tenant/project RLS.

Revision ID: 0002_s1_identity_rls
Revises: 0001_s1_storage
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002_s1_identity_rls"
down_revision = "0001_s1_storage"
branch_labels = None
depends_on = None

TENANT_TABLES = ("tenant_registry", "tenant_membership")
PROJECT_TABLES = (
    "project_registry",
    "project_membership",
    "runtime_task",
    "runtime_checkpoint",
    "artifact_record",
    "knowledge_embedding",
)


def _tenant_expression() -> str:
    return "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid"


def _project_expression() -> str:
    return (
        f"{_tenant_expression()} AND "
        "project_id = NULLIF(current_setting('app.project_id', true), '')::uuid"
    )


def _enable_policy(table: str, expression: str) -> None:
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


def upgrade() -> None:
    op.create_table(
        "tenant_registry",
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("display_name", sa.String(256), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('ACTIVE','SUSPENDED','DISABLED')",
            name="ck_tenant_registry_status",
        ),
        sa.PrimaryKeyConstraint("tenant_id", name="pk_tenant_registry"),
    )
    op.create_table(
        "project_registry",
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("display_name", sa.String(256), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('ACTIVE','SUSPENDED','CLOSED')",
            name="ck_project_registry_status",
        ),
        sa.PrimaryKeyConstraint("tenant_id", "project_id", name="pk_project_registry"),
    )
    op.create_table(
        "tenant_membership",
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("oidc_subject", sa.String(512), nullable=False),
        sa.Column("role_codes", postgresql.JSONB(), nullable=False),
        sa.Column("permission_version", sa.String(128), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('ACTIVE','SUSPENDED','REVOKED')",
            name="ck_tenant_membership_status",
        ),
        sa.PrimaryKeyConstraint("tenant_id", "user_id", name="pk_tenant_membership"),
        sa.UniqueConstraint(
            "tenant_id",
            "oidc_subject",
            name="uq_tenant_membership_tenant_subject",
        ),
    )
    op.create_table(
        "project_membership",
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role_codes", postgresql.JSONB(), nullable=False),
        sa.Column("permission_version", sa.String(128), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('ACTIVE','SUSPENDED','REVOKED')",
            name="ck_project_membership_status",
        ),
        sa.PrimaryKeyConstraint(
            "tenant_id",
            "project_id",
            "user_id",
            name="pk_project_membership",
        ),
    )
    for table in TENANT_TABLES:
        _enable_policy(table, _tenant_expression())
    for table in PROJECT_TABLES:
        _enable_policy(table, _project_expression())


def downgrade() -> None:
    for table in reversed(PROJECT_TABLES):
        _disable_policy(table)
    for table in reversed(TENANT_TABLES):
        _disable_policy(table)
    op.drop_table("project_membership")
    op.drop_table("tenant_membership")
    op.drop_table("project_registry")
    op.drop_table("tenant_registry")
