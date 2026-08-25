"""Add scoped knowledge release journal and atomic publication head.

Revision ID: 0011_s3_knowledge_release
Revises: 0010_s2_lifecycle
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0011_s3_knowledge_release"
down_revision = "0010_s2_lifecycle"
branch_labels = None
depends_on = None

EVENT = "knowledge_release_event"
PUBLICATION = "knowledge_publication"
HEAD = "knowledge_corpus_head"


def _scope_columns() -> tuple[sa.Column[Any], ...]:
    return (
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("permission_version", sa.String(128), nullable=False),
        sa.Column("role_codes", postgresql.JSONB(), nullable=False),
    )


def upgrade() -> None:
    op.create_table(
        EVENT,
        *_scope_columns(),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("aggregate_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("aggregate_type", sa.String(32), nullable=False),
        sa.Column("sequence", sa.BigInteger(), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("payload_sha256", sa.String(64), nullable=False),
        sa.Column("previous_sha256", sa.String(64), nullable=False),
        sa.Column("event_sha256", sa.String(64), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("sequence >= 1", name="ck_knowledge_release_event_sequence"),
        sa.CheckConstraint(
            "aggregate_type IN ('CANDIDATE','PUBLICATION','ACTION')",
            name="ck_knowledge_release_event_aggregate_type",
        ),
        sa.PrimaryKeyConstraint("tenant_id", "project_id", "event_id"),
        sa.UniqueConstraint(
            "tenant_id",
            "project_id",
            "user_id",
            "permission_version",
            "aggregate_id",
            "sequence",
            name="uq_knowledge_release_event_sequence",
        ),
    )
    op.create_table(
        PUBLICATION,
        *_scope_columns(),
        sa.Column("publication_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("candidate_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("corpus_id", sa.String(128), nullable=False),
        sa.Column("corpus_version", sa.String(64), nullable=False),
        sa.Column("index_version", sa.String(64), nullable=False),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("candidate_sha256", sa.String(64), nullable=False),
        sa.Column("publication_payload", postgresql.JSONB(), nullable=False),
        sa.Column("publication_sha256", sa.String(64), nullable=False),
        sa.Column("approval_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("review_manifest_sha256", sa.String(64), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "state IN ('PUBLISHED','SUPERSEDED','WITHDRAWN')",
            name="ck_knowledge_publication_state",
        ),
        sa.PrimaryKeyConstraint("tenant_id", "project_id", "publication_id"),
    )
    op.create_index(
        "ix_knowledge_publication_corpus",
        PUBLICATION,
        ["tenant_id", "project_id", "user_id", "permission_version", "corpus_id", "state"],
    )
    op.create_table(
        HEAD,
        *_scope_columns(),
        sa.Column("corpus_id", sa.String(128), nullable=False),
        sa.Column("publication_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("publication_sha256", sa.String(64), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint(
            "tenant_id",
            "project_id",
            "user_id",
            "permission_version",
            "corpus_id",
            name="pk_knowledge_corpus_head",
        ),
    )
    expression = (
        "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid AND "
        "project_id = NULLIF(current_setting('app.project_id', true), '')::uuid AND "
        "user_id = NULLIF(current_setting('app.user_id', true), '')::uuid AND "
        "permission_version = NULLIF(current_setting('app.permission_version', true), '')"
    )
    for table in (EVENT, PUBLICATION, HEAD):
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
            "CREATE FUNCTION deny_knowledge_release_event_mutation() RETURNS trigger "
            "LANGUAGE plpgsql AS $$ BEGIN "
            "RAISE EXCEPTION 'knowledge release events are append-only'; END; $$"
        )
    )
    op.execute(
        sa.text(
            f"CREATE TRIGGER knowledge_release_event_append_only "
            f"BEFORE UPDATE OR DELETE ON {EVENT} "
            "FOR EACH ROW EXECUTE FUNCTION deny_knowledge_release_event_mutation()"
        )
    )


def downgrade() -> None:
    op.execute(sa.text(f"DROP TRIGGER IF EXISTS knowledge_release_event_append_only ON {EVENT}"))
    op.execute(sa.text("DROP FUNCTION IF EXISTS deny_knowledge_release_event_mutation()"))
    for table in (HEAD, PUBLICATION, EVENT):
        op.execute(sa.text(f"DROP POLICY IF EXISTS scope_isolation ON {table}"))
        op.execute(sa.text(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY"))
        op.execute(sa.text(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY"))
    op.drop_table(HEAD)
    op.drop_index("ix_knowledge_publication_corpus", table_name=PUBLICATION)
    op.drop_table(PUBLICATION)
    op.drop_table(EVENT)
