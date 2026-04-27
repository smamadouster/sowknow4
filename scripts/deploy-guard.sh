#!/bin/bash
# Deployment guard — prevents deploying uncommitted changes to production
# Usage: source scripts/deploy-guard.sh || exit 1

set -e

CHANGED_FILES=$(git diff --name-only)
STAGED_FILES=$(git diff --cached --name-only)

if [ -n "$CHANGED_FILES" ] || [ -n "$STAGED_FILES" ]; then
    echo "========================================="
    echo "❌ DEPLOYMENT BLOCKED"
    echo "========================================="
    echo ""
    echo "You have uncommitted changes in the working tree:"
    echo ""
    if [ -n "$CHANGED_FILES" ]; then
        echo "Unstaged:"
        echo "$CHANGED_FILES" | sed 's/^/  - /'
    fi
    if [ -n "$STAGED_FILES" ]; then
        echo "Staged:"
        echo "$STAGED_FILES" | sed 's/^/  - /'
    fi
    echo ""
    echo "Commit (and push) before deploying to avoid drift between"
    echo "the running containers and the repository."
    echo ""
    echo "To bypass this guard (not recommended):"
    echo "  git stash && deploy ... && git stash pop"
    echo "========================================="
    exit 1
fi

echo "✅ Working tree clean — safe to deploy."
