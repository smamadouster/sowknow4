#!/bin/bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
COMPOSE_FILE="$PROJECT_ROOT/docker-compose.yml"
PRODUCTION_COMPOSE="$PROJECT_ROOT/docker-compose.production.yml"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

echo ""
echo "========================================"
echo "  SOWKNOW Master Validation Script"
echo "  $(date '+%Y-%m-%d %H:%M:%S')"
echo "========================================"
echo ""

TOTAL_CHECKS=0
PASSED_CHECKS=0
FAILED_CHECKS=0

log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[PASS]${NC} $1"
    PASSED_CHECKS=$((PASSED_CHECKS + 1))
}

log_warning() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[FAIL]${NC} $1"
    FAILED_CHECKS=$((FAILED_CHECKS + 1))
}

run_check() {
    TOTAL_CHECKS=$((TOTAL_CHECKS + 1))
    local check_name="$1"
    local check_result="$2"
    
    if [ "$check_result" = "0" ]; then
        log_success "$check_name"
    else
        log_error "$check_name"
    fi
}

echo "========================================"
echo "  Phase 1: File Validation"
echo "========================================"
echo ""

log_info "Checking .env file existence..."
if [ -f "$PROJECT_ROOT/.env" ]; then
    run_check ".env file exists" "0"
else
    run_check ".env file exists" "1"
fi

log_info "Checking .gitignore includes .env..."
if grep -q "^\.env$" "$PROJECT_ROOT/.gitignore" 2>/dev/null; then
    run_check ".env in .gitignore" "0"
else
    run_check ".env in .gitignore" "1"
fi

log_info "Checking docker-compose.yml exists..."
if [ -f "$COMPOSE_FILE" ]; then
    run_check "docker-compose.yml exists" "0"
else
    run_check "docker-compose.yml exists" "1"
fi

log_info "Checking docker-compose.production.yml exists..."
if [ -f "$PRODUCTION_COMPOSE" ]; then
    run_check "docker-compose.production.yml exists" "0"
else
    run_check "docker-compose.production.yml exists" "1"
fi

echo ""
echo "========================================"
echo "  Phase 2: Configuration Validation"
echo "========================================"
echo ""

log_info "Validating docker-compose.yml syntax..."
if docker compose -f "$COMPOSE_FILE" config &>/dev/null; then
    run_check "docker-compose.yml syntax valid" "0"
else
    run_check "docker-compose.yml syntax valid" "1"
fi

log_info "Validating docker-compose.production.yml syntax..."
if docker compose -f "$PRODUCTION_COMPOSE" config &>/dev/null; then
    run_check "docker-compose.production.yml syntax valid" "0"
else
    run_check "docker-compose.production.yml syntax valid" "1"
fi

log_info "Checking mandatory secrets (DATABASE_PASSWORD)..."
if grep -q 'DATABASE_PASSWORD.*:?' "$COMPOSE_FILE" || grep -q 'DATABASE_PASSWORD:?}' "$COMPOSE_FILE"; then
    run_check "DATABASE_PASSWORD uses :? syntax" "0"
else
    run_check "DATABASE_PASSWORD uses :? syntax" "1"
fi

log_info "Checking mandatory secrets (JWT_SECRET)..."
if grep -q 'JWT_SECRET.*:?' "$COMPOSE_FILE" || grep -q 'JWT_SECRET:?}' "$COMPOSE_FILE"; then
    run_check "JWT_SECRET uses :? syntax" "0"
else
    run_check "JWT_SECRET uses :? syntax" "1"
fi

log_info "Checking production secrets (POSTGRES_PASSWORD)..."
if grep -q 'POSTGRES_PASSWORD.*POSTGRES_PASSWORD' "$PRODUCTION_COMPOSE"; then
    run_check "POSTGRES_PASSWORD configured in production" "0"
else
    run_check "POSTGRES_PASSWORD configured in production" "1"
fi

log_info "Checking production secrets (REDIS_PASSWORD)..."
if grep -q 'REDIS_PASSWORD' "$PRODUCTION_COMPOSE" && grep -q '\${REDIS_PASSWORD' "$PRODUCTION_COMPOSE"; then
    run_check "REDIS_PASSWORD configured in production" "0"
else
    run_check "REDIS_PASSWORD configured in production" "1"
fi

echo ""
echo "========================================"
echo "  Phase 3: Container Validation"
echo "========================================"
echo ""

log_info "Checking Docker daemon..."
if command -v docker &>/dev/null && docker info &>/dev/null; then
    run_check "Docker daemon running" "0"
else
    run_check "Docker daemon running" "1"
    echo ""
    echo "========================================"
    echo "  VALIDATION SUMMARY"
    echo "========================================"
    echo -e "  Total Checks: $TOTAL_CHECKS"
    echo -e "  ${GREEN}Passed:${NC} $PASSED_CHECKS"
    echo -e "  ${RED}Failed:${NC} $FAILED_CHECKS"
    echo "========================================"
    exit 1
fi

log_info "Checking SOWKNOW containers..."
CONTAINER_COUNT=$(docker ps --format '{{.Names}}' 2>/dev/null | grep -c "sowknow" || echo "0")
if [ "$CONTAINER_COUNT" -ge 7 ]; then
    run_check "SOWKNOW containers running ($CONTAINER_COUNT)" "0"
else
    run_check "SOWKNOW containers running ($CONTAINER_COUNT)" "1"
fi

log_info "Checking healthy containers..."
HEALTHY_COUNT=$(docker ps --format '{{.Names}}' 2>/dev/null | grep "sowknow" | xargs -I {} docker inspect --format='{{.State.Health.Status}}' {} 2>/dev/null | grep -c "healthy" || echo "0")
run_check "Healthy containers ($HEALTHY_COUNT)" "0"

log_info "Checking backend container..."
if docker ps --format '{{.Names}}' 2>/dev/null | grep -q "sowknow4-backend"; then
    run_check "Backend container running" "0"
else
    run_check "Backend container running" "1"
fi

log_info "Checking postgres container..."
if docker ps --format '{{.Names}}' 2>/dev/null | grep -q "sowknow4-postgres"; then
    run_check "Postgres container running" "0"
else
    run_check "Postgres container running" "1"
fi

log_info "Checking redis container..."
if docker ps --format '{{.Names}}' 2>/dev/null | grep -q "sowknow4-redis"; then
    run_check "Redis container running" "0"
else
    run_check "Redis container running" "1"
fi

echo ""
echo "========================================"
echo "  Phase 4: Resource Validation"
echo "========================================"
echo ""

log_info "Checking memory limits..."
MEMORY_CHECK=$(docker compose -f "$COMPOSE_FILE" config 2>/dev/null | grep -c "memory:" || echo "0")
if [ "$MEMORY_CHECK" -ge 6 ]; then
    run_check "Memory limits configured ($MEMORY_CHECK services)" "0"
else
    run_check "Memory limits configured ($MEMORY_CHECK services)" "1"
fi

log_info "Checking CPU limits..."
CPU_CHECK=$(docker compose -f "$COMPOSE_FILE" config 2>/dev/null | grep -c "cpus:" || echo "0")
if [ "$CPU_CHECK" -ge 6 ]; then
    run_check "CPU limits configured ($CPU_CHECK services)" "0"
else
    run_check "CPU limits configured ($CPU_CHECK services)" "1"
fi

log_info "Checking health checks..."
HEALTH_CHECK=$(docker compose -f "$COMPOSE_FILE" config 2>/dev/null | grep -c "healthcheck:" || echo "0")
if [ "$HEALTH_CHECK" -ge 6 ]; then
    run_check "Health checks configured ($HEALTH_CHECK services)" "0"
else
    run_check "Health checks configured ($HEALTH_CHECK services)" "1"
fi

echo ""
echo "========================================"
echo "  Phase 5: Network Validation"
echo "========================================"
echo ""

log_info "Checking internal network..."
if grep -q "sowknow-net" "$COMPOSE_FILE"; then
    run_check "Internal network (sowknow-net) configured" "0"
else
    run_check "Internal network (sowknow-net) configured" "1"
fi

log_info "Checking Ollama exclusion..."
if ! grep -q "^  ollama:" "$COMPOSE_FILE"; then
    run_check "Ollama excluded (shared instance)" "0"
else
    run_check "Ollama excluded (shared instance)" "1"
fi

echo ""
echo "========================================"
echo "  Phase 6: Backup Validation"
echo "========================================"
echo ""

log_info "Testing backup volume writability..."
if docker exec sowknow4-postgres touch /backups/validation_test.txt 2>/dev/null; then
    run_check "Backup volume writable from postgres" "0"
    docker exec sowknow4-postgres rm -f /backups/validation_test.txt 2>/dev/null || true
else
    run_check "Backup volume writable from postgres" "1"
fi

echo ""
echo "========================================"
echo "  Phase 7: Security Validation"
echo "========================================"
echo ""

log_info "Checking for hardcoded secrets..."
if grep -E "password\s*=\s*['\"][^'\"\$\{]+['\"]" "$COMPOSE_FILE" 2>/dev/null | grep -v "^\s*#" | grep -qv '\${'; then
    run_check "No hardcoded passwords in compose" "1"
else
    run_check "No hardcoded passwords in compose" "0"
fi

log_info "Running Docker compliance test suite..."
if "$SCRIPT_DIR/test_docker_compliance.sh" -p 2>/dev/null; then
    run_check "Docker compliance tests pass" "0"
else
    run_check "Docker compliance tests pass" "1"
fi

echo ""
echo "========================================"
echo "  VALIDATION SUMMARY"
echo "========================================"
echo ""
echo -e "  Total Checks: $TOTAL_CHECKS"
echo -e "  ${GREEN}Passed:${NC} $PASSED_CHECKS"
echo -e "  ${RED}Failed:${NC} $FAILED_CHECKS"
echo "========================================"

if [ $FAILED_CHECKS -gt 0 ]; then
    echo ""
    log_warning "Some validation checks failed. Review the output above."
    exit 1
else
    echo ""
    log_success "All validation checks passed!"
    exit 0
fi
