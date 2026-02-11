#!/bin/bash

# SOWKNOW Security Test Runner
# This script runs the security test suite and generates a report

set -e

echo "========================================="
echo "SOWKNOW Security Test Suite"
echo "========================================="
echo ""

# Activate virtual environment
cd /root/development/src/active/sowknow4/backend
source venv/bin/activate

# Set Python path
export PYTHONPATH=/root/development/src/active/sowknow4/backend:$PYTHONPATH

# Set test environment variables
export JWT_SECRET="test-secret-key-for-security-testing"
export GEMINI_API_KEY="test-key"
export REDIS_URL="redis://localhost:6379/0"

# Create results directory
mkdir -p test_results

echo "1. Running Token Security Tests..."
echo "-----------------------------------"
pytest tests/security/test_token_security.py -v --tb=short \
    --html=test_results/token_security.html \
    --self-contained-html \
    2>&1 | tee test_results/token_security.log

echo ""
echo "2. Running RBAC Definition Tests..."
echo "-----------------------------------"
pytest tests/security/test_rbac_standalone.py::TestUserRoleDefinitions -v --tb=short \
    --html=test_results/rbac_definitions.html \
    --self-contained-html \
    2>&1 | tee test_results/rbac_definitions.log

echo ""
echo "3. Running Bucket Definition Tests..."
echo "-----------------------------------"
pytest tests/security/test_rbac_standalone.py::TestDocumentBucketDefinitions -v --tb=short \
    --html=test_results/bucket_definitions.html \
    --self-contained-html \
    2>&1 | tee test_results/bucket_definitions.log

echo ""
echo "4. Running Bucket Isolation Tests..."
echo "-----------------------------------"
pytest tests/security/test_rbac_standalone.py::TestDocumentBucketIsolation -v --tb=short \
    --html=test_results/bucket_isolation.html \
    --self-contained-html \
    2>&1 | tee test_results/bucket_isolation.log

echo ""
echo "========================================="
echo "Security Test Summary"
echo "========================================="
echo ""
echo "Test results saved to: test_results/"
echo "  - token_security.log/html"
echo "  - rbac_definitions.log/html"
echo "  - bucket_definitions.log/html"
echo "  - bucket_isolation.log/html"
echo ""
echo "For detailed analysis, see:"
echo "  tests/security/TEST_SUMMARY.md"
echo ""
