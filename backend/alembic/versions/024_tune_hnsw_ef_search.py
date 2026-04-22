"""Tune HNSW ef_search for better recall

Revision ID: 024
Revises: 023
Create Date: 2026-04-22

Increasing ef_search from the default (~40) to 100 improves recall
with a modest latency trade-off. For a vault product, finding the
right document matters more than raw speed.
"""

from alembic import op

revision = "024"
down_revision = "023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER INDEX sowknow.ix_document_chunks_embedding_hnsw SET (ef_search = 100)"
    )
    op.execute(
        "ALTER INDEX sowknow.ix_articles_embedding_vector SET (ef_search = 100)"
    )


def downgrade() -> None:
    op.execute(
        "ALTER INDEX sowknow.ix_document_chunks_embedding_hnsw SET (ef_search = 40)"
    )
    op.execute(
        "ALTER INDEX sowknow.ix_articles_embedding_vector SET (ef_search = 40)"
    )
