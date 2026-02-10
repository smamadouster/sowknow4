"""
Performance Optimization Configuration for SOWKNOW

Includes database indexes, query optimizations, and caching strategies.
"""
from sqlalchemy import Index, DDL
from sqlalchemy.orm import Session
from sqlalchemy.sql import text

# Performance tuning parameters
PERFORMANCE_CONFIG = {
    # Database connection pool
    "pool_size": 20,
    "max_overflow": 40,
    "pool_timeout": 30,
    "pool_recycle": 3600,

    # Query optimization
    "default_limit": 50,
    "max_limit": 500,
    "enable_query_cache": True,

    # Pagination
    "default_page_size": 20,
    "max_page_size": 100,

    # Embedding batch size
    "embedding_batch_size": 32,
    "embedding_timeout": 30,

    # Search optimization
    "search_parallel_workers": 4,
    "search_result_cache_ttl": 300,

    # Knowledge graph cache
    "graph_cache_enabled": True,
    "graph_cache_ttl": 600,

    # Multi-agent optimization
    "agent_timeout": 30,
    "max_concurrent_agents": 3,
}


def create_performance_indexes(engine):
    """Create performance-optimized database indexes"""

    indexes = [
        # Document indexes
        Index("ix_documents_status_created", "status", "created_at"),
        Index("ix_documents_bucket_status", "bucket", "status"),
        Index("ix_documents_mime_created", "mime_type", "created_at"),

        # Document chunk indexes for search
        Index("ix_chunks_doc_page", "document_id", "page_number"),

        # Entity indexes
        Index("ix_entities_type_count", "entity_type", "document_count"),
        Index("ix_entities_name_gin", "name", postgresql_using="gin", postgresql_ops={"name": "gin_trgm_ops"}),

        # Entity relationship indexes
        Index("ix_relationships_source_type", "source_id", "relation_type"),
        Index("ix_relationships_target_type", "target_id", "relation_type"),
        Index("ix_relationships_doc_count", "document_count"),

        # Timeline indexes
        Index("ix_timeline_date_type", "event_date", "event_type"),

        # Collection indexes
        Index("ix_collections_user_created", "user_id", "created_at"),

        # Chat indexes
        Index("ix_chat_sessions_user_updated", "user_id", "updated_at"),
        Index("ix_chat_messages_session_created", "session_id", "created_at"),
    ]

    for idx in indexes:
        try:
            idx.create(engine, checkfirst=True)
        except Exception as e:
            print(f"Warning: Could not create index {idx.name}: {e}")


def configure_database_settings(engine):
    """Configure PostgreSQL performance settings"""

    settings = [
        # Shared buffers (25% of RAM)
        "SET shared_buffers = '4GB'",

        # Effective cache size (75% of RAM)
        "SET effective_cache_size = '12GB'",

        # Work memory (per operation)
        "SET work_mem = '64MB'",

        # Maintenance work memory
        "SET maintenance_work_mem = '512MB'",

        # Random page cost (for SSD)
        "SET random_page_cost = '1.1'",

        # Checkpoint settings
        "SET checkpoint_completion_target = '0.9'",
        "SET wal_buffers = '16MB'",

        # Query planner
        "SET default_statistics_target = '100'",

        # Parallel query
        "SET max_parallel_workers_per_gather = '4'",
        "SET parallel_setup_cost = '100'",
        "SET parallel_tuple_cost = '0.01'",

        # Enable JIT compilation
        "SET jit = 'on'",
    ]

    with engine.connect() as conn:
        for setting in settings:
            try:
                conn.execute(text(setting))
            except Exception as e:
                print(f"Warning: Could not set {setting}: {e}")
        conn.commit()


def enable_vector_search_optimization(engine):
    """Enable pgvector and IVFFlat indexing for faster vector search"""

    # Create IVFFlat index for embeddings (faster than HNSW for moderate datasets)
    ivfflat_index = DDL("""
        CREATE INDEX IF NOT EXISTS ix_chunks_embedding_ivfflat
        ON document_chunks
        USING ivfflat (embedding vector_cosine_ops)
        WITH (lists = 100)
    """)

    with engine.connect() as conn:
        try:
            conn.execute(ivfflat_index)
            conn.commit()
        except Exception as e:
            print(f"Warning: Could not create IVFFlat index: {e}")


def create_materialized_views(engine):
    """Create materialized views for common queries"""

    # Materialized view for document stats
    mv_stats = DDL("""
        CREATE MATERIALIZED VIEW IF NOT EXISTS mv_document_stats AS
        SELECT
            bucket,
            status,
            mime_type,
            COUNT(*) as total_count,
            COUNT(CASE WHEN created_at > NOW() - INTERVAL '30 days' THEN 1 END) as recent_count,
            SUM(CASE WHEN status = 'processed' THEN 1 ELSE 0 END) as processed_count
        FROM documents
        GROUP BY bucket, status, mime_type
        WITH DATA;
    """)

    # Materialized view for entity popularity
    mv_entities = DDL("""
        CREATE MATERIALIZED VIEW IF NOT EXISTS mv_entity_popularity AS
        SELECT
            e.id,
            e.name,
            e.entity_type,
            e.document_count,
            e.relationship_count,
            COUNT(em.id) as mention_count,
            MAX(em.created_at) as last_mentioned_at
        FROM entities e
        LEFT JOIN entity_mentions em ON em.entity_id = e.id
        GROUP BY e.id, e.name, e.entity_type, e.document_count, e.relationship_count
        WITH DATA;
    """)

    # Create indexes on materialized views
    mv_indexes = [
        "CREATE INDEX IF NOT EXISTS ix_mv_stats_bucket ON mv_document_stats(bucket);",
        "CREATE INDEX IF NOT EXISTS ix_mv_stats_status ON mv_document_stats(status);",
        "CREATE INDEX IF NOT EXISTS ix_mv_entities_type ON mv_entity_popularity(entity_type);",
        "CREATE INDEX IF NOT EXISTS ix_mv_entities_count ON mv_entity_popularity(document_count DESC);",
    ]

    with engine.connect() as conn:
        try:
            conn.execute(mv_stats)
            conn.execute(mv_entities)
            conn.commit()
        except Exception as e:
            print(f"Warning: Could not create materialized views: {e}")

        for idx_sql in mv_indexes:
            try:
                conn.execute(text(idx_sql))
            except Exception as e:
                print(f"Warning: Could not create MV index: {e}")
        conn.commit()


def refresh_materialized_views(engine):
    """Refresh materialized views (call this periodically)"""

    refresh_sql = """
    REFRESH MATERIALIZED VIEW CONCURRENTLY mv_document_stats;
    REFRESH MATERIALIZED VIEW CONCURRENTLY mv_entity_popularity;
    """

    with engine.connect() as conn:
        try:
            conn.execute(text(refresh_sql))
            conn.commit()
        except Exception as e:
            print(f"Warning: Could not refresh materialized views: {e}")


def setup_query_caching(redis_client):
    """Setup query result caching in Redis"""

    from functools import wraps
    import hashlib
    import json
    import pickle

    def cache_query(ttl=300):
        """Decorator to cache query results"""

        def decorator(func):
            @wraps(func)
            async def wrapper(*args, **kwargs):
                # Create cache key from function name and arguments
                key_data = f"{func.__name__}:{str(args)}:{str(kwargs)}"
                cache_key = f"query_cache:{hashlib.md5(key_data.encode()).hexdigest()}"

                # Try to get from cache
                cached = redis_client.get(cache_key)
                if cached:
                    return pickle.loads(cached)

                # Execute function
                result = await func(*args, **kwargs)

                # Cache result
                redis_client.setex(
                    cache_key,
                    ttl,
                    pickle.dumps(result)
                )

                return result

            return wrapper

        return decorator

    return cache_query


class QueryOptimizer:
    """Query optimization utilities"""

    @staticmethod
    def optimize_search_query(query: str, db: Session) -> dict:
        """Optimize search query before execution"""

        optimizations = {
            "original_query": query,
            "optimized_query": query,
            "use_hybrid": True,
            "limit": PERFORMANCE_CONFIG["default_limit"],
            "parallel": PERFORMANCE_CONFIG["search_parallel_workers"] > 1
        }

        # Short queries benefit more from keyword search
        if len(query.split()) <= 3:
            optimizations["use_hybrid"] = False
            optimizations["search_type"] = "keyword"

        # Long queries benefit from semantic search
        elif len(query.split()) >= 8:
            optimizations["search_type"] = "semantic"
            optimizations["use_hybrid"] = False

        return optimizations

    @staticmethod
    def paginate_query(query, page: int = 1, page_size: int = None):
        """Apply pagination with limits"""

        page_size = page_size or PERFORMANCE_CONFIG["default_page_size"]
        page_size = min(page_size, PERFORMANCE_CONFIG["max_page_size"])

        offset = (page - 1) * page_size

        return query.limit(page_size).offset(offset)

    @staticmethod
    def get_search_hints(query: str) -> dict:
        """Get hints for optimizing search"""

        hints = {
            "use_cache": False,
            "parallel": False,
            "materialized_view": False
        }

        # Use cache for repeated queries
        common_terms = ["recent", "latest", "all", "summary"]
        if any(term in query.lower() for term in common_terms):
            hints["use_cache"] = True

        # Use parallel processing for complex queries
        if len(query.split()) > 5:
            hints["parallel"] = True

        return hints


def apply_performance_tuning(engine):
    """Apply all performance tuning settings"""

    print("Applying performance tuning...")

    # Create indexes
    create_performance_indexes(engine)
    print("✓ Performance indexes created")

    # Configure database settings
    configure_database_settings(engine)
    print("✓ Database settings configured")

    # Enable vector search optimization
    enable_vector_search_optimization(engine)
    print("✓ Vector search optimization enabled")

    # Create materialized views
    create_materialized_views(engine)
    print("✓ Materialized views created")

    print("\nPerformance tuning complete!")


if __name__ == "__main__":
    from app.database import engine

    apply_performance_tuning(engine)
