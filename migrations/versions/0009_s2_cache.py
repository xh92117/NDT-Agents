"""Add versioned scoped S2 cache entries.

Revision ID: 0009_s2_cache
Revises: 0008_s2_restore
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0009_s2_cache"
down_revision = "0008_s2_restore"
branch_labels = None
depends_on = None

TABLE = "cache_entry"


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("permission_version", sa.String(128), nullable=False),
        sa.Column("cache_class", sa.String(32), nullable=False),
        sa.Column("cache_key_sha256", sa.String(64), nullable=False),
        sa.Column("cache_entry_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("value", postgresql.JSONB(), nullable=False),
        sa.Column("value_sha256", sa.String(64), nullable=False),
        sa.Column("version_manifest", postgresql.JSONB(), nullable=False),
        sa.Column("provenance", postgresql.JSONB(), nullable=False),
        sa.Column("validation_state", sa.String(32), nullable=False),
        sa.Column("saved_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "cache_class IN ('EXACT','RETRIEVAL','TOOL','PARSE','SEMANTIC')",
            name="ck_cache_entry_class",
        ),
        sa.CheckConstraint(
            "validation_state IN ('VALID','STALE','REJECTED')",
            name="ck_cache_entry_state",
        ),
        sa.PrimaryKeyConstraint(
            "tenant_id",
            "project_id",
            "user_id",
            "permission_version",
            "cache_class",
            "cache_key_sha256",
            name="pk_cache_entry",
        ),
        sa.UniqueConstraint(
            "tenant_id", "project_id", "cache_entry_id", name="uq_cache_entry_identity"
        ),
    )
    op.create_index("ix_cache_entry_expiry", TABLE, ["tenant_id", "project_id", "expires_at"])
    expression = (
        "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid AND "
        "project_id = NULLIF(current_setting('app.project_id', true), '')::uuid AND "
        "user_id = NULLIF(current_setting('app.user_id', true), '')::uuid AND "
        "permission_version = NULLIF(current_setting('app.permission_version', true), '')"
    )
    op.execute(sa.text(f"ALTER TABLE {TABLE} ENABLE ROW LEVEL SECURITY"))
    op.execute(sa.text(f"ALTER TABLE {TABLE} FORCE ROW LEVEL SECURITY"))
    op.execute(
        sa.text(
            f"CREATE POLICY scope_isolation ON {TABLE} "
            f"USING ({expression}) WITH CHECK ({expression})"
        )
    )


def downgrade() -> None:
    op.execute(sa.text(f"DROP POLICY IF EXISTS scope_isolation ON {TABLE}"))
    op.execute(sa.text(f"ALTER TABLE {TABLE} NO FORCE ROW LEVEL SECURITY"))
    op.execute(sa.text(f"ALTER TABLE {TABLE} DISABLE ROW LEVEL SECURITY"))
    op.drop_index("ix_cache_entry_expiry", table_name=TABLE)
    op.drop_table(TABLE)
