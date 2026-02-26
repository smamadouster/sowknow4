#!/usr/bin/env bash
# =============================================================================
# SOWKNOW — First-Time Environment Setup Script
# =============================================================================
# Copies .env.example to .env and auto-generates all required secrets.
# Run once on a fresh checkout before docker compose up.
#
# Usage:
#   chmod +x scripts/setup_env.sh
#   ./scripts/setup_env.sh
#
# The script is idempotent: if .env already exists it will NOT overwrite it.
# =============================================================================

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="$REPO_ROOT/backend/.env"
EXAMPLE_FILE="$REPO_ROOT/backend/.env.example"

if [[ ! -f "$EXAMPLE_FILE" ]]; then
  echo "ERROR: $EXAMPLE_FILE not found — are you in the right directory?" >&2
  exit 1
fi

if [[ -f "$ENV_FILE" ]]; then
  echo "INFO: $ENV_FILE already exists — skipping (delete it first to regenerate)."
  exit 0
fi

echo "Copying $EXAMPLE_FILE → $ENV_FILE …"
cp "$EXAMPLE_FILE" "$ENV_FILE"

# --------------------------------------------------------------------------
# Auto-generate secrets
# --------------------------------------------------------------------------

generate_secret() {
  openssl rand -hex 32
}

generate_password() {
  openssl rand -base64 24 | tr -d '=+/' | head -c 32
}

echo "Generating secrets …"

# JWT secret (openssl rand — required by CREDENTIAL_ROTATION_LOG guidance)
JWT_SECRET=$(generate_secret)
sed -i "s|YOUR_JWT_SECRET_HERE|${JWT_SECRET}|g" "$ENV_FILE"
echo "  ✅  JWT_SECRET generated"

# Database password
DB_PASS=$(generate_password)
sed -i "s|YOUR_DATABASE_PASSWORD_HERE|${DB_PASS}|g" "$ENV_FILE"
echo "  ✅  DATABASE_PASSWORD generated"

# Redis password
REDIS_PASS=$(generate_password)
sed -i "s|YOUR_REDIS_PASSWORD_HERE|${REDIS_PASS}|g" "$ENV_FILE" 2>/dev/null || true
echo "  ✅  REDIS_PASSWORD generated (set manually if placeholder not found)"

# Bot API key
BOT_KEY=$(generate_secret)
sed -i "s|YOUR_BOT_API_KEY_HERE|${BOT_KEY}|g" "$ENV_FILE"
echo "  ✅  BOT_API_KEY generated"

# --------------------------------------------------------------------------
# Remind user about keys they must supply manually
# --------------------------------------------------------------------------

echo ""
echo "========================================================"
echo "  ⚠️  Manual steps required — add your API keys to:"
echo "  $ENV_FILE"
echo "========================================================"
echo ""
echo "  MOONSHOT_API_KEY    — https://platform.moonshot.cn"
echo "  MINIMAX_API_KEY     — https://platform.minimaxi.com"
echo "  OPENROUTER_API_KEY  — https://openrouter.ai/keys"
echo "  TELEGRAM_BOT_TOKEN  — @BotFather on Telegram"
echo "  ADMIN_EMAIL         — your admin email"
echo "  ADMIN_PASSWORD      — choose a strong password"
echo ""
echo "Done. Run: docker compose up -d"
