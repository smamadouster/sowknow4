"""Fold accents in full-text search vectors (document_chunks + articles)

French text is the vault default, and accents are semantically significant,
so search must work whether the user types "presence" or "presence". PostgreSQL
tsvector keeps accented lexemes ('presence' -> 'presenc', 'présence' ->
'présenc'), so a query without accents silently missed every accented body
match (verified live 2026-08-04: 'presence' returned 0 hits vs 'présence'
hitting thousands of rows).

This migration:
- Installs the unaccent extension into the sowknow schema (the DB user's
  search_path puts 'sowknow' first, so a bare CREATE EXTENSION would land
  there anyway — pin it explicitly for determinism).
- Rewrites ALL search_vector trigger functions (chunk + article) to wrap
  text in sowknow.unaccent() BEFORE stemming, and to resolve the regconfig
  SAFELY by name (production has ~600k chunks with search_language='unknown'
  which is not a regconfig and a bare `::regconfig` cast aborts the write).

The backfill of existing rows is intentionally NOT part of this migration: the
app keeps BOTH accented and unaccented @@ branches, so search is correct for
old and new rows at every point of the transition, and the row rewrite is
slow on this table (bloated heap + huge HNSW index → heavy buffer churn). The
backfill runs as an explicit, resumable ops step instead:
`scripts/migration036_backfill.py` (id-ordered batches, commits each batch).

No index rebuild is required: the GIN index is on the stored column, not an
expression, so updating the column value updates the index incrementally.
unaccent() is only needed IMMUTABLE for expression indexes — it is not used
in one here.

Revision: 036_search_vector_unaccent
"""

import logging

from alembic import op

logger = logging.getLogger("alembic.runtime.migration")

revision = "036_search_vector_unaccent"
down_revision = "035_collection_orchestration"
branch_labels = None
depends_on = None

# Deterministic unaccent function reference. The extension is installed in the
# sowknow schema (see module docstring) and the app search SQL uses the same
# fully-qualified name.
UNACCENT = "sowknow.unaccent"

# Resolve the tsvector config safely. Production has ~600k chunks with
# search_language = 'unknown' (a legacy language-detection default that is NOT
# a PostgreSQL regconfig); a bare `search_language::regconfig` cast aborts on
# those rows. Look the config up by name via pg_ts_config and fall back to
# 'french' when absent — robust for any invalid value, not just 'unknown'.
_SAFE_CFG_NEW = """COALESCE(
    (SELECT cfgname::regconfig FROM pg_ts_config WHERE cfgname = COALESCE(NEW.search_language, 'french')),
    'french'::regconfig
)"""

# The trigger actually ATTACHED to document_chunks (schema drift: the original
# migration-009 trigger was replaced by `trg_update_chunk_search_vector` which
# calls this CASE-based function). It must be rewritten too or new inserts
# would keep producing accent-sensitive vectors.
_CHUNK_TRIGGER_FN = f"""CREATE OR REPLACE FUNCTION sowknow.update_chunk_search_vector()
RETURNS TRIGGER AS $$
BEGIN
    NEW.search_vector := to_tsvector(
        {_SAFE_CFG_NEW},
        sowknow.unaccent(COALESCE(NEW.chunk_text, ''))
    );
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;"""

# Migration-009 function (kept for consistency; not attached today).
_MIG009_CHUNK_TRIGGER_FN = f"""CREATE OR REPLACE FUNCTION sowknow_update_chunk_search_vector()
RETURNS TRIGGER AS $$
BEGIN
    NEW.search_vector := to_tsvector(
        {_SAFE_CFG_NEW},
        sowknow.unaccent(COALESCE(NEW.chunk_text, ''))
    );
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;"""

_ARTICLE_TRIGGER_FN = f"""CREATE OR REPLACE FUNCTION sowknow.articles_search_vector_update()
RETURNS trigger AS $$
BEGIN
    NEW.search_vector :=
        setweight(to_tsvector({_SAFE_CFG_NEW}, sowknow.unaccent(COALESCE(NEW.title, ''))), 'A') ||
        setweight(to_tsvector({_SAFE_CFG_NEW}, sowknow.unaccent(COALESCE(NEW.summary, ''))), 'B') ||
        setweight(to_tsvector({_SAFE_CFG_NEW}, sowknow.unaccent(COALESCE(NEW.body, ''))), 'C');
    NEW.updated_at := NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;"""


def upgrade() -> None:
    # 1. Unaccent extension pinned to the app schema.
    op.execute("CREATE EXTENSION IF NOT EXISTS unaccent WITH SCHEMA sowknow")

    # 2. Chunk trigger(s) — fold accents before stemming, safe regconfig.
    op.execute(_CHUNK_TRIGGER_FN)
    op.execute(_MIG009_CHUNK_TRIGGER_FN)

    # 3. Article trigger — same fold on title/summary/body (migration 014).
    op.execute(_ARTICLE_TRIGGER_FN)

    # 4. No backfill here — run scripts/migration036_backfill.py as an
    #    explicit, resumable ops step (see module docstring for why).
    logger.info(
        "migration 036 trigger rewrite complete — run scripts/migration036_backfill.py "
        "to re-stem existing search_vector rows"
    )


def downgrade() -> None:
    # Restore the pre-036 trigger functions (accented lexemes) — data stays
    # unaccented until an explicit backfill, matching the forward direction.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION sowknow.update_chunk_search_vector()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.search_vector := to_tsvector(
                CASE NEW.search_language
                    WHEN 'french' THEN 'french'::regconfig
                    WHEN 'english' THEN 'english'::regconfig
                    ELSE 'simple'::regconfig
                END,
                NEW.chunk_text
            );
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION sowknow_update_chunk_search_vector()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.search_vector := to_tsvector(
                COALESCE(NEW.search_language, 'french')::regconfig,
                COALESCE(NEW.chunk_text, '')
            );
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION sowknow.articles_search_vector_update()
        RETURNS trigger AS $$
        BEGIN
            NEW.search_vector :=
                setweight(to_tsvector(NEW.search_language::regconfig, COALESCE(NEW.title, '')), 'A') ||
                setweight(to_tsvector(NEW.search_language::regconfig, COALESCE(NEW.summary, '')), 'B') ||
                setweight(to_tsvector(NEW.search_language::regconfig, COALESCE(NEW.body, '')), 'C');
            NEW.updated_at := NOW();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
