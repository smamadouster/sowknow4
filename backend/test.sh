#!/usr/bin/env bash
# Run the SOWKNOW test suite with proper environment setup.
#
# Usage:
#   ./test.sh                    # Run all SQLite-safe tests
#   ./test.sh --postgres         # Run with PostgreSQL (spins up test container)
#   ./test.sh --unit             # Run only unit tests
#   ./test.sh --integration      # Run only integration tests (needs postgres)
#   ./test.sh --e2e              # Run only E2E tests (needs postgres)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# Default to SQLite-safe tests
USE_POSTGRES=false
PYTEST_ARGS=("-x" "-v")

while [[ $# -gt 0 ]]; do
    case $1 in
        --postgres)
            USE_POSTGRES=true
            shift
            ;;
        --unit)
            PYTEST_ARGS+=("tests/unit/")
            shift
            ;;
        --integration)
            USE_POSTGRES=true
            PYTEST_ARGS+=("tests/integration/")
            shift
            ;;
        --e2e)
            USE_POSTGRES=true
            PYTEST_ARGS+=("tests/e2e/")
            shift
            ;;
        *)
            PYTEST_ARGS+=("$1")
            shift
            ;;
    esac
done

# Default to all tests if no specific directory given
if [[ ${#PYTEST_ARGS[@]} -eq 2 ]]; then
    PYTEST_ARGS+=("tests/")
fi

if [[ "$USE_POSTGRES" == true ]]; then
    echo "🐘 Starting PostgreSQL test container..."
    docker-compose -f "$PROJECT_ROOT/docker-compose.test.yml" up -d postgres-test

    # Wait for postgres to be healthy
    for i in {1..30}; do
        if docker exec sowknow4-postgres-test pg_isready -U sowknow_test >/dev/null 2>&1; then
            echo "✅ PostgreSQL test container ready"
            break
        fi
        echo "⏳ Waiting for PostgreSQL... ($i/30)"
        sleep 1
    done

    export DATABASE_URL="postgresql://sowknow_test:testpass@localhost:5433/sowknow_test"
    export TEST_DATABASE_URL="$DATABASE_URL"
fi

# Always set test JWT secret
export JWT_SECRET="${JWT_SECRET:-test-secret-key-not-for-production}"
export APP_ENV="test"

cd "$SCRIPT_DIR"
echo "🧪 Running: pytest ${PYTEST_ARGS[*]}"
python -m pytest "${PYTEST_ARGS[@]}"
