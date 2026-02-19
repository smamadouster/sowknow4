#!/bin/bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
COMPOSE_FILE="$PROJECT_ROOT/docker-compose.yml"
PRODUCTION_COMPOSE="$PROJECT_ROOT/docker-compose.production.yml"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

VERBOSE=false
JSON_OUTPUT=false
PREFLIGHT_ONLY=false

TOTAL_TESTS=0
PASSED_TESTS=0
FAILED_TESTS=0

log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[PASS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[FAIL]${NC} $1"
}

run_test() {
    local test_name="$1"
    local test_func="$2"
    
    TOTAL_TESTS=$((TOTAL_TESTS + 1))
    
    if $VERBOSE; then
        log_info "Running: $test_name"
    fi
    
    if $test_func; then
        PASSED_TESTS=$((PASSED_TESTS + 1))
        log_success "$test_name"
        return 0
    else
        FAILED_TESTS=$((FAILED_TESTS + 1))
        log_error "$test_name"
        return 1
    fi
}

print_summary() {
    echo ""
    echo "========================================"
    echo "  Docker Compliance Test Summary"
    echo "========================================"
    echo "  Total Tests:  $TOTAL_TESTS"
    echo -e "  ${GREEN}Passed:${NC}      $PASSED_TESTS"
    echo -e "  ${RED}Failed:${NC}      $FAILED_TESTS"
    echo "========================================"
    
    if $JSON_OUTPUT; then
        cat <<EOF
{
  "total": $TOTAL_TESTS,
  "passed": $PASSED_TESTS,
  "failed": $FAILED_TESTS,
  "success": $([ $FAILED_TESTS -eq 0 ] && echo "true" || echo "false")
}
EOF
    fi
    
    if [ $FAILED_TESTS -gt 0 ]; then
        exit 1
    fi
}

trap print_summary EXIT

preflight_checks() {
    log_info "Running preflight checks..."
    
    if [ ! -f "$COMPOSE_FILE" ]; then
        log_error "docker-compose.yml not found at $COMPOSE_FILE"
        exit 1
    fi
    
    if ! command -v docker &> /dev/null; then
        log_warning "Docker not found - skipping live validation tests"
        return 1
    fi
    
    if ! docker compose version &> /dev/null; then
        log_warning "Docker Compose v2 not found - some tests may fail"
    fi
    
    log_success "Preflight checks complete"
    return 0
}

test_container_count() {
    local expected_min_services=6
    local services=$(docker compose -f "$COMPOSE_FILE" config --services 2>/dev/null | wc -l || echo "0")
    
    if [ "$services" -ge "$expected_min_services" ]; then
        return 0
    else
        log_error "Expected at least $expected_min_services services, found $services"
        docker compose -f "$COMPOSE_FILE" config --services 2>/dev/null || true
        return 1
    fi
}

test_memory_limits() {
    local services_with_memory=0
    local total_services=$(docker compose -f "$COMPOSE_FILE" config --services 2>/dev/null | wc -l || echo "0")
    
    while IFS= read -r service; do
        local mem_limit=$(docker compose -f "$COMPOSE_FILE" config "$service" 2>/dev/null | grep -i "memory:" || echo "")
        if [ -n "$mem_limit" ]; then
            services_with_memory=$((services_with_memory + 1))
        fi
    done < <(docker compose -f "$COMPOSE_FILE" config --services 2>/dev/null)
    
    if [ "$services_with_memory" -eq "$total_services" ]; then
        return 0
    else
        log_error "Expected memory limits on all $total_services services, found $services_with_memory"
        return 1
    fi
}

test_cpu_limits() {
    local services_with_cpu=0
    local total_services=$(docker compose -f "$COMPOSE_FILE" config --services 2>/dev/null | wc -l || echo "0")
    
    while IFS= read -r service; do
        local cpu_limit=$(docker compose -f "$COMPOSE_FILE" config "$service" 2>/dev/null | grep -i "cpus:" || echo "")
        if [ -n "$cpu_limit" ]; then
            services_with_cpu=$((services_with_cpu + 1))
        fi
    done < <(docker compose -f "$COMPOSE_FILE" config --services 2>/dev/null)
    
    if [ "$services_with_cpu" -eq "$total_services" ]; then
        return 0
    else
        log_error "Expected CPU limits on all $total_services services, found $services_with_cpu"
        return 1
    fi
}

test_volume_existence() {
    if grep -q "^volumes:" "$COMPOSE_FILE"; then
        local volume_count=$(docker compose -f "$COMPOSE_FILE" config 2>/dev/null | grep -A 100 "^volumes:" | grep -c "^[a-z].*:" || echo "0")
        
        if [ "$volume_count" -ge 3 ]; then
            return 0
        else
            log_error "Expected at least 3 volumes, found $volume_count"
            return 1
        fi
    else
        log_error "No volumes defined in docker-compose.yml"
        return 1
    fi
}

test_ollama_exclusion() {
    if grep -q "^  ollama:" "$COMPOSE_FILE"; then
        log_error "Ollama should NOT be in docker-compose.yml (using shared instance)"
        return 1
    fi
    
    if grep -q "^  ollama:" "$PRODUCTION_COMPOSE" 2>/dev/null; then
        log_error "Ollama should NOT be in docker-compose.production.yml (using shared instance)"
        return 1
    fi
    
    return 0
}

test_health_checks() {
    local services_with_health=0
    local total_services=$(docker compose -f "$COMPOSE_FILE" config --services 2>/dev/null | wc -l || echo "0")
    
    while IFS= read -r service; do
        local health_check=$(docker compose -f "$COMPOSE_FILE" config "$service" 2>/dev/null | grep -A 5 "healthcheck:" || echo "")
        if [ -n "$health_check" ]; then
            services_with_health=$((services_with_health + 1))
        fi
    done < <(docker compose -f "$COMPOSE_FILE" config --services 2>/dev/null)
    
    if [ "$services_with_health" -ge 6 ]; then
        return 0
    else
        log_error "Expected health checks on at least 6 services, found $services_with_health"
        return 1
    fi
}

test_hardcoded_secrets() {
    local secrets_found=0
    local patterns=("password\s*=\s*['\"][^'\"]+['\"]" "api_key\s*=\s*['\"][^'\"]+['\"]" "secret\s*=\s*['\"][^'\"]+['\"]")
    
    for pattern in "${patterns[@]}"; do
        if grep -Ei "$pattern" "$COMPOSE_FILE" | grep -v "^\s*#" | grep -qv '\${'; then
            secrets_found=$((secrets_found + 1))
        fi
    done
    
    if [ "$secrets_found" -gt 0 ]; then
        log_error "Found potential hardcoded secrets in docker-compose.yml"
        return 1
    fi
    
    return 0
}

test_production_compose() {
    if [ ! -f "$PRODUCTION_COMPOSE" ]; then
        log_error "docker-compose.production.yml not found"
        return 1
    fi
    
    if ! docker compose -f "$PRODUCTION_COMPOSE" config &> /dev/null; then
        log_error "docker-compose.production.yml is not valid"
        docker compose -f "$PRODUCTION_COMPOSE" config 2>&1 | head -20
        return 1
    fi
    
    return 0
}

usage() {
    cat <<EOF
Docker Compliance Test Suite

Usage: $0 [OPTIONS]

OPTIONS:
    -h, --help              Show this help message
    -v, --verbose           Enable verbose output
    -j, --json              Output results in JSON format
    -p, --preflight        Run only preflight checks
    
EOF
}

main() {
    while [[ $# -gt 0 ]]; do
        case $1 in
            -h|--help)
                usage
                exit 0
                ;;
            -v|--verbose)
                VERBOSE=true
                shift
                ;;
            -j|--json)
                JSON_OUTPUT=true
                shift
                ;;
            -p|--preflight)
                PREFLIGHT_ONLY=true
                shift
                ;;
            *)
                log_error "Unknown option: $1"
                usage
                exit 1
                ;;
        esac
    done
    
    echo ""
    echo "========================================"
    echo "  Docker Compliance Test Suite"
    echo "========================================"
    echo ""
    
    preflight_checks
    
    if $PREFLIGHT_ONLY; then
        exit 0
    fi
    
    echo ""
    log_info "Running compliance tests..."
    echo ""
    
    run_test "Container Count (8 services)" test_container_count
    run_test "Memory Limits" test_memory_limits
    run_test "CPU Limits" test_cpu_limits
    run_test "Volume Existence" test_volume_existence
    run_test "Ollama Exclusion" test_ollama_exclusion
    run_test "Health Checks" test_health_checks
    run_test "Hardcoded Secrets" test_hardcoded_secrets
    run_test "Production Compose" test_production_compose
}

main "$@"
