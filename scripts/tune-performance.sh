#!/bin/bash
# SOWKNOW Performance Tuning Script

echo "========================================="
echo "SOWKNOW Performance Tuning"
echo "========================================="

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "\n${YELLOW}1. Running database performance tuning...${NC}"

if [ -f "backend/app/performance.py" ]; then
    docker-compose -f docker-compose.yml run --rm backend python -c "
from app.performance import apply_performance_tuning
from app.database import engine
apply_performance_tuning(engine)
"
    echo -e "${GREEN}✓ Database tuning applied${NC}"
else
    echo "⚠ Performance module not found"
fi

echo -e "\n${YELLOW}2. Analyzing table sizes...${NC}"

docker-compose -f docker-compose.yml run --rm backend python -c "
from app.database import engine
from sqlalchemy import text

with engine.connect() as conn:
    result = conn.execute(text('''
        SELECT
            schemaname,
            tablename,
            pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) as size
        FROM pg_tables
        WHERE schemaname = 'sowknow'
        ORDER BY pg_total_relation_size(schemaname||'.'||tablename) DESC
    '''))
    for row in result:
        print(f'  {row[1]}: {row[2]}')
"

echo -e "\n${YELLOW}3. Checking index usage...${NC}"

docker-compose -f docker-compose.yml run --rm backend python -c "
from app.database import engine
from sqlalchemy import text

with engine.connect() as conn:
    result = conn.execute(text('''
        SELECT
            schemaname,
            tablename,
            indexname,
            idx_scan as index_scans,
            pg_size_pretty(pg_relation_size(indexrelid)) as index_size
        FROM pg_stat_user_indexes
        WHERE schemaname = 'sowknow'
        ORDER BY idx_scan ASC
        LIMIT 10
    '''))
    print('  Least used indexes:')
    for row in result:
        print(f'    {row[2]}: {row[3]} scans ({row[4]})')
"

echo -e "\n${YELLOW}4. Checking slow queries...${NC}"

docker-compose -f docker-compose.yml run --rm backend python -c "
from app.database import engine
from sqlalchemy import text

with engine.connect() as conn:
    result = conn.execute(text('''
        SELECT
            query,
            calls,
            mean_exec_time as avg_time_ms,
            max_exec_time as max_time_ms
        FROM pg_stat_statements
        WHERE query NOT LIKE '%pg_stat%'
        ORDER BY mean_exec_time DESC
        LIMIT 5
    '''))
    print('  Slowest queries:')
    for row in result:
        query_preview = row[0][:100] if row[0] else 'N/A'
        print(f'    {query_preview}...')
        print(f'      Calls: {row[1]}, Avg: {row[2]:.2f}ms, Max: {row[3]:.2f}ms')
"

echo -e "\n${YELLOW}5. Vacuum and analyze tables...${NC}"

docker-compose -f docker-compose.yml run --rm backend python -c "
from app.database import engine
from sqlalchemy import text

with engine.connect() as conn:
    tables = ['documents', 'document_chunks', 'entities', 'entity_relationships',
              'entity_mentions', 'timeline_events', 'collections']

    for table in tables:
        try:
            conn.execute(text(f'VACUUM ANALYZE sowknow.{table}'))
            conn.commit()
            print(f'  ✓ {table}')
        except Exception as e:
            print(f'  ✗ {table}: {e}')
"

echo -e "\n${YELLOW}6. Refreshing materialized views...${NC}"

docker-compose -f docker-compose.yml run --rm backend python -c "
from app.performance import refresh_materialized_views
from app.database import engine
refresh_materialized_views(engine)
print('  ✓ Materialized views refreshed')
"

echo -e "\n${GREEN}Performance tuning complete!${NC}"
echo ""
echo "Recommendations:"
echo "1. Schedule regular VACUUM ANALYZE (daily during low traffic)"
echo "2. Monitor slow queries with pg_stat_statements"
echo "3. Consider partitioning large tables by date"
echo "4. Enable connection pooling in production"
echo "5. Use Redis for session and query caching"
