#!/usr/bin/env bash
# SOWKNOW Static Code & Security Audit
# Run from the project root directory
set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
PASS() { echo -e "${GREEN}[PASS]${NC} $1"; }
FAIL() { echo -e "${RED}[FAIL]${NC} $1"; FAILURES=$((FAILURES+1)); }
WARN() { echo -e "${YELLOW}[WARN]${NC} $1"; }
SECTION() { echo -e "\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n  $1\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"; }
FAILURES=0

SECTION "1. GIT HYGIENE"
# .env in .gitignore
if grep -q "^\.env$" .gitignore 2>/dev/null || grep -q "^\.env" .gitignore 2>/dev/null; then
  PASS ".env is in .gitignore"
else
  FAIL ".env is NOT in .gitignore — secrets may be committed!"
fi

# No .env files committed
if git ls-files | grep -q "^\.env$"; then
  FAIL ".env file is tracked by git — remove it and rotate all secrets"
else
  PASS "No .env file tracked by git"
fi

# Secret scan in git history
echo "  Scanning git history for secrets..."
if git log --all -p 2>/dev/null | grep -iE "(api_key|secret_key|password|access_token|bearer)" \
   | grep -v "placeholder\|example\|REPLACE\|your_" | head -5 | grep -q .; then
  FAIL "Potential secrets found in git history — run git-filter-repo to clean"
else
  PASS "No obvious secrets detected in git history"
fi

SECTION "2. PYTHON — LINT & SECURITY"
# Detect backend dir (where pyproject.toml / ruff config lives)
PYTHON_DIR="."
if [ -f "backend/pyproject.toml" ] || [ -d "backend/app" ]; then
  PYTHON_DIR="backend"
fi

if command -v ruff &>/dev/null; then
  RUFF_OUT=$(cd "$PYTHON_DIR" && ruff check . --quiet 2>&1 || true)
  if echo "$RUFF_OUT" | grep -qE "^[A-Za-z].*error|Found [0-9]+ error"; then
    FAIL "Ruff found lint errors in $PYTHON_DIR — run: cd $PYTHON_DIR && ruff check ."
    echo "$RUFF_OUT" | head -10
  else
    PASS "Ruff lint: 0 errors in $PYTHON_DIR"
  fi
else
  WARN "ruff not installed — run: pip install ruff"
fi

if command -v bandit &>/dev/null; then
  # Exclude venv, test directories, and generated files from security scan
  # Use --severity-level high to report ONLY High-severity findings (not Medium)
  BANDIT_RESULT=$(bandit -r "$PYTHON_DIR/app" --severity-level high -q \
    --exclude "$PYTHON_DIR/venv,$PYTHON_DIR/.venv" 2>&1)
  # Count issues — if output contains "Issue:" it found something
  if echo "$BANDIT_RESULT" | grep -q "^>> Issue:"; then
    FAIL "Bandit found HIGH severity security issues in app code"
    echo "$BANDIT_RESULT" | grep -E "Issue:|Location:|CWE:" | head -15
  else
    PASS "Bandit: 0 HIGH severity security issues in app code"
  fi
else
  WARN "bandit not installed — run: pip install bandit"
fi

if command -v pip-audit &>/dev/null; then
  PIP_AUDIT_DIR="$PYTHON_DIR"
  if [ -f "$PYTHON_DIR/requirements.txt" ]; then
    PIP_AUDIT_OUT=$(pip-audit -r "$PYTHON_DIR/requirements.txt" --quiet 2>&1 || true)
  else
    PIP_AUDIT_OUT=$(pip-audit --quiet 2>&1 || true)
  fi
  if echo "$PIP_AUDIT_OUT" | grep -qE "CRITICAL|HIGH"; then
    FAIL "pip-audit found HIGH/CRITICAL CVEs in Python dependencies"
    echo "$PIP_AUDIT_OUT" | grep -E "CRITICAL|HIGH" | head -10
  else
    PASS "pip-audit: no HIGH/CRITICAL CVEs in Python deps"
  fi
else
  WARN "pip-audit not installed — run: pip install pip-audit"
fi

# Check for hardcoded secrets patterns in Python files (exclude venv and test files)
echo "  Scanning Python files for hardcoded secrets..."
if grep -rn --include="*.py" -E "(api_key\s*=\s*['\"][a-zA-Z0-9]{20,}|password\s*=\s*['\"][^'\"]{8,})" \
   --exclude-dir=".git" --exclude-dir="node_modules" --exclude-dir="venv" --exclude-dir=".venv" 2>/dev/null \
   | grep -v "os\.getenv\|os\.environ\|getenv\|test\|example\|placeholder" | grep -q .; then
  FAIL "Potential hardcoded secrets found in Python source — use os.getenv() instead"
else
  PASS "No hardcoded secrets pattern detected in Python files"
fi

# Check LLM routing — no direct Moonshot HTTP calls outside llm_router.py / kimi_service.py
# (kimi_service.py is the service implementation that llm_router delegates to — expected)
echo "  Checking LLM routing discipline..."
MOONSHOT_CALLS=$(grep -rn --include="*.py" "moonshot\|MOONSHOT_API_KEY\|moonshotai" \
  --exclude-dir=".git" --exclude-dir="venv" --exclude-dir=".venv" --exclude-dir="tests" \
  --exclude="llm_router.py" --exclude="kimi_service.py" --exclude="*.env*" \
  --exclude="monitoring.py" --exclude="openrouter_service.py" 2>/dev/null \
  | grep -v "sowknow_audit\|sowknow_static" | wc -l)
if [ "$MOONSHOT_CALLS" -gt 0 ]; then
  FAIL "Moonshot API references found outside approved files ($MOONSHOT_CALLS occurrences) — privacy routing may be bypassed"
  grep -rn --include="*.py" "moonshot\|MOONSHOT_API_KEY" \
    --exclude-dir=".git" --exclude-dir="venv" --exclude-dir=".venv" --exclude-dir="tests" \
    --exclude="llm_router.py" --exclude="kimi_service.py" --exclude="monitoring.py" \
    --exclude="openrouter_service.py" 2>/dev/null | grep -v "sowknow_audit\|sowknow_static" | head -10
else
  PASS "Moonshot API calls confined to approved service files (llm_router.py, kimi_service.py, openrouter_service.py)"
fi

# Check for f-string SQL injection patterns (exclude venv)
if grep -rn --include="*.py" -E "f\"SELECT|f'SELECT|f\"INSERT|f'INSERT|f\"UPDATE|f'UPDATE|f\"DELETE|f'DELETE" \
   --exclude-dir=".git" --exclude-dir="venv" --exclude-dir=".venv" 2>/dev/null | grep -q .; then
  FAIL "Potential SQL injection: f-string SQL queries found — use parameterized queries"
else
  PASS "No f-string SQL patterns detected"
fi

SECTION "3. TYPESCRIPT / FRONTEND"
if command -v npx &>/dev/null && [ -f "frontend/tsconfig.json" ]; then
  cd frontend 2>/dev/null || true
  if npx tsc --noEmit 2>&1 | grep -q "error TS"; then
    FAIL "TypeScript: compilation errors found — run: npx tsc --noEmit"
  else
    PASS "TypeScript: 0 compilation errors"
  fi
  if npx eslint . --quiet 2>&1 | grep -q "error"; then
    FAIL "ESLint: errors found — run: npx eslint ."
  else
    PASS "ESLint: 0 errors"
  fi
  if npm audit --audit-level=high 2>&1 | grep -qE "HIGH|CRITICAL"; then
    FAIL "npm audit: HIGH/CRITICAL vulnerabilities in Node.js dependencies"
  else
    PASS "npm audit: no HIGH/CRITICAL CVEs in Node.js deps"
  fi
  # Check for any types (exclude .next/ build output which is auto-generated)
  ANY_COUNT=$(grep -rn --include="*.ts" --include="*.tsx" ": any" \
    --exclude-dir=".git" --exclude-dir="node_modules" --exclude-dir=".next" 2>/dev/null \
    | grep -v "//.*: any" | wc -l)
  if [ "$ANY_COUNT" -gt 0 ]; then
    WARN "$ANY_COUNT 'any' type usages found in source files — consider typing properly for production"
    grep -rn --include="*.ts" --include="*.tsx" ": any" \
      --exclude-dir=".git" --exclude-dir="node_modules" --exclude-dir=".next" 2>/dev/null \
      | grep -v "//.*: any" | head -10
  else
    PASS "Zero 'any' TypeScript types found in source files"
  fi
  cd .. 2>/dev/null || true
else
  WARN "Frontend directory or TypeScript not found — adjust path as needed"
fi

SECTION "4. DOCKER & INFRASTRUCTURE"
if [ -f "docker-compose.yml" ]; then
  PASS "docker-compose.yml exists"
  # Memory limits
  if grep -q "mem_limit\|memory:" docker-compose.yml; then
    PASS "Docker memory limits configured in docker-compose.yml"
  else
    FAIL "No memory limits in docker-compose.yml — risk of VPS OOM"
  fi
  # Restart policies
  if grep -q "restart:" docker-compose.yml; then
    PASS "Restart policies configured in docker-compose.yml"
  else
    FAIL "No restart policies in docker-compose.yml"
  fi
  # Health checks
  HEALTH_COUNT=$(grep -c "healthcheck:" docker-compose.yml 2>/dev/null || echo 0)
  SERVICES=$(grep -c "^  [a-z]" docker-compose.yml 2>/dev/null || echo 1)
  if [ "$HEALTH_COUNT" -gt 0 ]; then
    PASS "Healthchecks defined for $HEALTH_COUNT service(s)"
  else
    WARN "No healthchecks in docker-compose.yml — add healthcheck: for each service"
  fi
else
  FAIL "docker-compose.yml not found"
fi

if [ -f "nginx.conf" ] || find . -name "nginx.conf" | grep -q .; then
  NGINX=$(find . -name "nginx.conf" | head -1)
  PASS "nginx.conf found: $NGINX"
  if grep -q "Strict-Transport-Security" "$NGINX"; then
    PASS "HSTS configured in nginx.conf"
  else
    FAIL "HSTS not configured in nginx.conf"
  fi
  if grep -q "limit_req_zone" "$NGINX"; then
    PASS "Rate limiting configured in nginx.conf"
  else
    FAIL "Rate limiting (limit_req_zone) not configured in nginx.conf"
  fi
  if grep -q "ssl_certificate" "$NGINX"; then
    PASS "SSL certificate configured in nginx.conf"
  else
    FAIL "No SSL certificate in nginx.conf"
  fi
  if grep -q "client_max_body_size" "$NGINX"; then
    PASS "Upload size limit configured in nginx.conf"
  else
    WARN "client_max_body_size not set in nginx.conf (default is 1MB — set to 100m)"
  fi
else
  FAIL "nginx.conf not found"
fi

SECTION "5. TEST COVERAGE"
# Detect backend directory (tests live there)
BACKEND_DIR=""
if [ -d "backend" ] && [ -f "backend/pytest.ini" ]; then
  BACKEND_DIR="backend"
elif [ -f "pytest.ini" ]; then
  BACKEND_DIR="."
fi

if [ -n "$BACKEND_DIR" ]; then
  # Try venv python, then system python3
  if [ -f "$BACKEND_DIR/venv/bin/python" ]; then
    PYTEST_BIN="$BACKEND_DIR/venv/bin/python"
  elif command -v python3 &>/dev/null; then
    PYTEST_BIN="python3"
  else
    PYTEST_BIN=""
  fi

  if [ -n "$PYTEST_BIN" ]; then
    echo "  Running unit tests in $BACKEND_DIR/tests/unit/ ..."
    PYTEST_OUT=$(cd "$BACKEND_DIR" && "$PYTEST_BIN" -m pytest tests/unit/ --tb=no -q 2>&1 | tail -5 || true)
    echo "  $PYTEST_OUT"
    if echo "$PYTEST_OUT" | grep -qE "passed"; then
      PASS "pytest unit tests: $(echo "$PYTEST_OUT" | grep -oE '[0-9]+ passed')"
    fi
    if echo "$PYTEST_OUT" | grep -qE "[0-9]+ failed"; then
      FAIL "pytest unit tests have failures: $(echo "$PYTEST_OUT" | grep -oE '[0-9]+ failed')"
    fi
  else
    WARN "No Python interpreter found — skipping pytest"
  fi

  # Count test files (exclude venv)
  TEST_COUNT=$(find "${BACKEND_DIR}/tests" -name "test_*.py" -not -path "*/venv/*" 2>/dev/null | wc -l)
  if [ "$TEST_COUNT" -ge 5 ]; then
    PASS "$TEST_COUNT test files found"
  else
    WARN "Only $TEST_COUNT test files found — aim for comprehensive test coverage"
  fi
else
  WARN "No pytest.ini found — cannot run tests"
fi

# Check LLM router test specifically
if find . -name "test_llm_router.py" -not -path "*/venv/*" | grep -q .; then
  PASS "test_llm_router.py exists — LLM routing tested"
else
  FAIL "test_llm_router.py missing — critical privacy routing has no tests"
fi

SECTION "6. ENVIRONMENT CONFIGURATION"
if [ -f ".env.example" ]; then
  PASS ".env.example exists (documents required env vars)"
  REQUIRED_VARS=(DATABASE_URL REDIS_URL MOONSHOT_API_KEY TENCENT_OCR_SECRET_ID TENCENT_OCR_SECRET_KEY OLLAMA_HOST TELEGRAM_BOT_TOKEN)
  for var in "${REQUIRED_VARS[@]}"; do
    if grep -q "^${var}=" .env.example; then
      PASS "  .env.example has: $var"
    else
      WARN "  .env.example missing: $var"
    fi
  done
else
  WARN ".env.example not found — document required environment variables"
fi

# ─── FINAL SUMMARY ─────────────────────────
echo -e "\n══════════════════════════════════════════"
echo "  STATIC AUDIT COMPLETE"
echo "══════════════════════════════════════════"
if [ "$FAILURES" -eq 0 ]; then
  echo -e "  ${GREEN}ALL CHECKS PASSED — $FAILURES failures${NC}"
  echo -e "  ${GREEN}Code base is production-ready ✓${NC}"
else
  echo -e "  ${RED}FAILURES: $FAILURES${NC}"
  echo -e "  ${RED}Resolve all failures before commercial launch${NC}"
  exit 1
fi
