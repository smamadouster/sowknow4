#!/bin/bash
# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  Sowknow Architecture Map Generator (Unified)                               ║
# ║  Generates cache.graph.* files for both backend (Python AST) and           ║
# ║  frontend (ts-morph) in a single command.                                   ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
AUDIT_DIR="${PROJECT_ROOT}/scripts/structural_audit"

echo "🧠 Sowknow Map-First Architecture Generator"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# ── Backend (Python AST) ─────────────────────────────────────────────────────
echo "📦 Backend: Python AST analysis..."
cd "${PROJECT_ROOT}"
python3 "${AUDIT_DIR}/generate_map_py.py"
echo ""

# ── Frontend (ts-morph) ──────────────────────────────────────────────────────
echo "🎨 Frontend: ts-morph analysis..."
cd "${PROJECT_ROOT}"
NODE_PATH="${PROJECT_ROOT}/frontend/node_modules" \
    node "${AUDIT_DIR}/generateMap.js"
echo ""

# ── Summary ──────────────────────────────────────────────────────────────────
echo "✅ All maps generated successfully."
echo ""
echo "Artifacts:"
ls -lh "${AUDIT_DIR}"/cache.graph.* | awk '{print "  → " $9 " (" $5 ")"}'
echo ""
echo "💡 Tip: Add these files to git to give agents persistent structural context."
