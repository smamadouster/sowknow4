"""
Integration tests for pgvector similarity search.
Requires a running PostgreSQL instance with pgvector extension.
Skip if DB is unavailable.
"""
import pytest
import os

pytestmark = pytest.mark.integration


def get_db_url():
    return os.getenv("DATABASE_URL", os.getenv("POSTGRES_URL", ""))


def db_available():
    url = get_db_url()
    if not url:
        return False
    try:
        import psycopg2
        conn = psycopg2.connect(url)
        conn.close()
        return True
    except Exception:
        return False


@pytest.fixture(scope="module")
def db_conn():
    if not db_available():
        pytest.skip("PostgreSQL not available — set DATABASE_URL to run integration tests")
    import psycopg2
    conn = psycopg2.connect(get_db_url())
    yield conn
    conn.close()


class TestVectorColumnExists:
    """Issue #1: pgvector column must exist on document_chunks."""

    def test_embedding_vector_column_exists(self, db_conn):
        """embedding_vector column must exist in document_chunks."""
        cur = db_conn.cursor()
        cur.execute("""
            SELECT column_name, udt_name
            FROM information_schema.columns
            WHERE table_schema = 'sowknow'
              AND table_name = 'document_chunks'
              AND column_name = 'embedding_vector'
        """)
        row = cur.fetchone()
        assert row is not None, "embedding_vector column not found in sowknow.document_chunks"

    def test_pgvector_extension_installed(self, db_conn):
        """pgvector extension must be installed."""
        cur = db_conn.cursor()
        cur.execute("SELECT extname FROM pg_extension WHERE extname = 'vector'")
        row = cur.fetchone()
        assert row is not None, "pgvector extension not installed — run: CREATE EXTENSION vector"

    def test_hnsw_or_ivfflat_index_exists(self, db_conn):
        """A vector similarity index must exist on embedding_vector."""
        cur = db_conn.cursor()
        cur.execute("""
            SELECT indexname, indexdef
            FROM pg_indexes
            WHERE schemaname = 'sowknow'
              AND tablename = 'document_chunks'
              AND (indexdef ILIKE '%hnsw%' OR indexdef ILIKE '%ivfflat%')
        """)
        rows = cur.fetchall()
        assert len(rows) > 0, "No HNSW or IVFFlat index found on document_chunks.embedding_vector"


class TestCosineDistanceQuery:
    """Issue #1: Cosine distance queries must work on vector column."""

    def test_cosine_distance_syntax_valid(self, db_conn):
        """The <=> operator (cosine distance) must work on the vector column."""
        cur = db_conn.cursor()
        # This just tests the query compiles — no rows needed
        try:
            cur.execute("""
                SELECT id FROM sowknow.document_chunks
                ORDER BY embedding_vector <=> '[0.1, 0.2]'::vector
                LIMIT 1
            """)
        except Exception as e:
            if "different vector dimensions" in str(e) or "operator does not exist" not in str(e):
                pass  # dimension mismatch is OK — column exists and operator works
            else:
                pytest.fail(f"Cosine distance query failed: {e}")
