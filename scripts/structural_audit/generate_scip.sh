#!/bin/bash
# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  Sowknow SCIP / LSIF Index Generator                                        ║
# ║  Generates code intelligence indexes for both backend (Python) and          ║
# ║  frontend (TypeScript) using Sourcegraph SCIP tools.                        ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
SCIP_DIR="${PROJECT_ROOT}/.context/scip"

echo "🧬 Sowknow SCIP Index Generator"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

mkdir -p "${SCIP_DIR}"

# ── Backend (Python via custom LSIF generator) ───────────────────────────────
echo "🐍 Backend: Python LSIF indexing..."
cd "${PROJECT_ROOT}"
python3 "${SCRIPT_DIR}/generate_lsif_py.py"

echo "   → ${SCIP_DIR}/backend.lsif"

# ── Frontend (TypeScript via scip-typescript) ────────────────────────────────
echo "🎨 Frontend: TypeScript SCIP indexing..."
cd "${PROJECT_ROOT}/frontend"
npx scip-typescript index \
    --output "${SCIP_DIR}/frontend.scip" \
    --cwd . \
    --no-progress-bar

echo "   → ${SCIP_DIR}/frontend.scip"

# ── Summary ──────────────────────────────────────────────────────────────────
echo ""
echo "✅ Code intelligence indexes generated successfully."
ls -lh "${SCIP_DIR}"/* | awk '{print "  → " $9 " (" $5 ")"}'
echo ""
echo "💡 These indexes enable precise code navigation in Sourcegraph,"
echo "   GitHub Code Search, and compatible language servers."
