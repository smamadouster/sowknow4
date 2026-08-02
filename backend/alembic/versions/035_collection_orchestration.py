"""Collection Orchestrator data-model foundation

Adds the Collection Orchestrator tables hanging off sowknow.smart_folders
(the collection request):

- ALTER smart_folders: idempotency_key, job_state, checkpoint,
  confirmed_params, celery_task_id (all nullable, additive)
- CREATE clarification_sessions, query_executions, source_items,
  annotations, factsets, analysis_results, insights, deliverables,
  collection_audit_events

All tables are new/empty — plain CREATE INDEX is safe (no CONCURRENTLY
needed).

Revision: 035_collection_orchestration
"""

from alembic import op
from sqlalchemy.dialects import postgresql
import sqlalchemy as sa

revision = "035_collection_orchestration"
down_revision = "034_chunk_bucket_denorm"
branch_labels = None
depends_on = None


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    ]


def upgrade() -> None:
    # ------------------------------------------------------------------
    # ALTER smart_folders (additive, all nullable)
    # ------------------------------------------------------------------
    op.add_column(
        "smart_folders",
        sa.Column("idempotency_key", sa.String(255), nullable=True),
        schema="sowknow",
    )
    op.add_column(
        "smart_folders",
        sa.Column("job_state", sa.String(50), nullable=True, server_default="draft"),
        schema="sowknow",
    )
    op.add_column(
        "smart_folders",
        sa.Column("checkpoint", postgresql.JSONB(), nullable=True),
        schema="sowknow",
    )
    op.add_column(
        "smart_folders",
        sa.Column("confirmed_params", postgresql.JSONB(), nullable=True),
        schema="sowknow",
    )
    op.add_column(
        "smart_folders",
        sa.Column("celery_task_id", sa.String(255), nullable=True),
        schema="sowknow",
    )
    op.create_index(
        "ix_smart_folders_idempotency_key",
        "smart_folders",
        ["idempotency_key"],
        schema="sowknow",
    )

    # ------------------------------------------------------------------
    # clarification_sessions
    # ------------------------------------------------------------------
    op.create_table(
        "clarification_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("rounds", postgresql.JSONB(), nullable=True, server_default="[]"),
        sa.Column("extracted_entities", postgresql.JSONB(), nullable=True, server_default="[]"),
        sa.Column("extracted_intent", sa.String(100), nullable=True),
        sa.Column("analysis_types", postgresql.JSONB(), nullable=True, server_default="[]"),
        sa.Column("open_ambiguities", postgresql.JSONB(), nullable=True, server_default="[]"),
        sa.Column("assumptions", postgresql.JSONB(), nullable=True, server_default="[]"),
        sa.Column("status", sa.String(30), nullable=True, server_default="active"),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["request_id"], ["sowknow.smart_folders.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        schema="sowknow",
    )
    op.create_index(
        "ix_clarification_sessions_request_id",
        "clarification_sessions",
        ["request_id"],
        schema="sowknow",
    )

    # ------------------------------------------------------------------
    # query_executions
    # ------------------------------------------------------------------
    op.create_table(
        "query_executions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("search_call_payload", postgresql.JSONB(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("result_count", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(30), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["request_id"], ["sowknow.smart_folders.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        schema="sowknow",
    )
    op.create_index(
        "ix_query_executions_request_id",
        "query_executions",
        ["request_id"],
        schema="sowknow",
    )

    # ------------------------------------------------------------------
    # source_items
    # ------------------------------------------------------------------
    op.create_table(
        "source_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("execution_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("uri", sa.String(1024), nullable=True),
        sa.Column("title", sa.String(512), nullable=True),
        sa.Column("item_type", sa.String(100), nullable=True),
        sa.Column("source", sa.String(100), nullable=True),
        sa.Column("author", sa.String(255), nullable=True),
        sa.Column("item_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("relevance_score", sa.Float(), nullable=True),
        sa.Column("snippet", sa.Text(), nullable=True),
        sa.Column("acl_stamp", sa.String(20), nullable=True),
        sa.Column("content_hash", sa.String(64), nullable=True),
        sa.Column("simhash", sa.String(32), nullable=True),
        sa.Column("canonical_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("rank_position", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(30), nullable=True, server_default="ok"),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["request_id"], ["sowknow.smart_folders.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["execution_id"], ["sowknow.query_executions.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        schema="sowknow",
    )
    op.create_index(
        "ix_source_items_request_id", "source_items", ["request_id"], schema="sowknow"
    )
    op.create_index(
        "ix_source_items_content_hash", "source_items", ["content_hash"], schema="sowknow"
    )

    # ------------------------------------------------------------------
    # annotations
    # ------------------------------------------------------------------
    op.create_table(
        "annotations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("item_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("annotation_text", sa.Text(), nullable=True),
        sa.Column("evidence_offsets", postgresql.JSONB(), nullable=True, server_default="[]"),
        sa.Column("category_tags", postgresql.JSONB(), nullable=True, server_default="[]"),
        sa.Column("rank_position", sa.Integer(), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["item_id"], ["sowknow.source_items.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        schema="sowknow",
    )
    op.create_index(
        "ix_annotations_item_id", "annotations", ["item_id"], schema="sowknow"
    )

    # ------------------------------------------------------------------
    # factsets
    # ------------------------------------------------------------------
    op.create_table(
        "factsets",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=True, server_default="1"),
        sa.Column("facts", postgresql.JSONB(), nullable=True, server_default="[]"),
        sa.Column(
            "normalization_notes", postgresql.JSONB(), nullable=True, server_default="[]"
        ),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["request_id"], ["sowknow.smart_folders.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        schema="sowknow",
    )
    op.create_index(
        "ix_factsets_request_id", "factsets", ["request_id"], schema="sowknow"
    )

    # ------------------------------------------------------------------
    # analysis_results
    # ------------------------------------------------------------------
    op.create_table(
        "analysis_results",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("factset_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("analysis_type", sa.String(50), nullable=True),
        sa.Column("inputs", postgresql.JSONB(), nullable=True),
        sa.Column("output", postgresql.JSONB(), nullable=True),
        sa.Column("thresholds_used", postgresql.JSONB(), nullable=True),
        sa.Column("provenance", postgresql.JSONB(), nullable=True, server_default="[]"),
        sa.Column("code_version", sa.String(50), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["factset_id"], ["sowknow.factsets.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        schema="sowknow",
    )
    op.create_index(
        "ix_analysis_results_factset_id",
        "analysis_results",
        ["factset_id"],
        schema="sowknow",
    )

    # ------------------------------------------------------------------
    # insights
    # ------------------------------------------------------------------
    op.create_table(
        "insights",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("analysis_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("statement", sa.Text(), nullable=True),
        sa.Column("source_refs", postgresql.JSONB(), nullable=True, server_default="[]"),
        sa.Column(
            "validation_status", sa.String(30), nullable=True, server_default="pending"
        ),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["analysis_id"], ["sowknow.analysis_results.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        schema="sowknow",
    )
    op.create_index(
        "ix_insights_analysis_id", "insights", ["analysis_id"], schema="sowknow"
    )

    # ------------------------------------------------------------------
    # deliverables
    # ------------------------------------------------------------------
    op.create_table(
        "deliverables",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=True, server_default="1"),
        sa.Column("summary_md", sa.Text(), nullable=True),
        sa.Column("item_list_ref", sa.String(1024), nullable=True),
        sa.Column("appendix", postgresql.JSONB(), nullable=True),
        sa.Column("exports", postgresql.JSONB(), nullable=True, server_default="[]"),
        sa.Column("disclosures", postgresql.JSONB(), nullable=True, server_default="[]"),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["request_id"], ["sowknow.smart_folders.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        schema="sowknow",
    )
    op.create_index(
        "ix_deliverables_request_id", "deliverables", ["request_id"], schema="sowknow"
    )

    # ------------------------------------------------------------------
    # collection_audit_events (append-only — own timestamp, no created/updated)
    # ------------------------------------------------------------------
    op.create_table(
        "collection_audit_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "timestamp",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("stage", sa.String(30), nullable=True),
        sa.Column("action", sa.String(100), nullable=True),
        sa.Column("input_ref", sa.String(1024), nullable=True),
        sa.Column("output_ref", sa.String(1024), nullable=True),
        sa.Column("component_version", sa.String(100), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(30), nullable=True),
        sa.Column("detail", postgresql.JSONB(), nullable=True),
        sa.ForeignKeyConstraint(
            ["request_id"], ["sowknow.smart_folders.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        schema="sowknow",
    )
    op.create_index(
        "ix_collection_audit_events_request_id",
        "collection_audit_events",
        ["request_id"],
        schema="sowknow",
    )
    op.create_index(
        "ix_collection_audit_events_timestamp",
        "collection_audit_events",
        ["timestamp"],
        schema="sowknow",
    )


def downgrade() -> None:
    # Reverse dependency order
    op.drop_table("collection_audit_events", schema="sowknow")
    op.drop_table("deliverables", schema="sowknow")
    op.drop_table("insights", schema="sowknow")
    op.drop_table("analysis_results", schema="sowknow")
    op.drop_table("factsets", schema="sowknow")
    op.drop_table("annotations", schema="sowknow")
    op.drop_table("source_items", schema="sowknow")
    op.drop_table("query_executions", schema="sowknow")
    op.drop_table("clarification_sessions", schema="sowknow")

    op.drop_index(
        "ix_smart_folders_idempotency_key", table_name="smart_folders", schema="sowknow"
    )
    op.drop_column("smart_folders", "celery_task_id", schema="sowknow")
    op.drop_column("smart_folders", "confirmed_params", schema="sowknow")
    op.drop_column("smart_folders", "checkpoint", schema="sowknow")
    op.drop_column("smart_folders", "job_state", schema="sowknow")
    op.drop_column("smart_folders", "idempotency_key", schema="sowknow")
