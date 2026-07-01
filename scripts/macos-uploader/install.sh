#!/usr/bin/env bash
#
# SOWKNOW macOS Upload Tools — Installer
#
# This script installs the SOWKNOW Auto-Uploader and Sync Agent on a Mac.
# Run it from the directory containing the package files:
#
#   cd macos-uploader
#   ./install.sh
#

set -euo pipefail

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

info() { echo -e "${BLUE}[info]${NC} $*"; }
success() { echo -e "${GREEN}[ok]${NC} $*"; }
warn() { echo -e "${YELLOW}[warn]${NC} $*"; }
error() { echo -e "${RED}[error]${NC} $*"; }

# Detect paths
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HOME_DIR="$HOME"
INSTALL_DIR="$HOME_DIR/.sowknow/bin"
LAUNCH_AGENTS_DIR="$HOME_DIR/Library/LaunchAgents"
LOGS_DIR="$HOME_DIR/Library/Logs"
PLIST_NAME="com.sowknow.autouploader.plist"
PLIST_PATH="$LAUNCH_AGENTS_DIR/$PLIST_NAME"

info "SOWKNOW macOS Upload Tools Installer"
echo ""

# Check macOS
if [[ "$(uname -s)" != "Darwin" ]]; then
    error "This installer is designed for macOS. Detected: $(uname -s)"
    exit 1
fi

# Check Python 3
if ! command -v python3 &>/dev/null; then
    error "python3 not found. Please install Python 3 from https://www.python.org/downloads/ or Xcode Command Line Tools."
    exit 1
fi

PYTHON_VERSION=$(python3 --version 2>&1 | awk '{print $2}')
info "Found Python $PYTHON_VERSION"

# Check pip3
if ! command -v pip3 &>/dev/null; then
    error "pip3 not found. Please install pip (usually bundled with Python 3)."
    exit 1
fi

# Install dependencies
info "Installing Python dependencies..."
pip3 install --user -q -r "$SCRIPT_DIR/requirements.txt" || {
    warn "pip3 install with --user failed, trying without --user..."
    pip3 install -q -r "$SCRIPT_DIR/requirements.txt"
}
success "Dependencies installed"

# Create directories
mkdir -p "$INSTALL_DIR"
mkdir -p "$LAUNCH_AGENTS_DIR"
mkdir -p "$LOGS_DIR"
mkdir -p "$HOME_DIR/Desktop/Public"
mkdir -p "$HOME_DIR/Desktop/Confidential"

# Install scripts
cp "$SCRIPT_DIR/sowknow-auto-uploader.py" "$INSTALL_DIR/sowknow-auto-uploader.py"
cp "$SCRIPT_DIR/sowknow_sync.py" "$INSTALL_DIR/sowknow_sync.py"
chmod +x "$INSTALL_DIR/sowknow-auto-uploader.py"
chmod +x "$INSTALL_DIR/sowknow_sync.py"
success "Scripts installed to $INSTALL_DIR"

# Add to PATH if needed
SHELL_RC=""
case "${SHELL##*/}" in
    zsh) SHELL_RC="$HOME_DIR/.zshrc" ;;
    bash) SHELL_RC="$HOME_DIR/.bashrc" ;;
    *) SHELL_RC="" ;;
esac

if [[ -n "$SHELL_RC" ]] && ! grep -q "$INSTALL_DIR" "$SHELL_RC" 2>/dev/null; then
    echo "export PATH=\"$INSTALL_DIR:\$PATH\"" >> "$SHELL_RC"
    success "Added $INSTALL_DIR to PATH in $SHELL_RC"
    info "Run 'source $SHELL_RC' or restart your terminal to use 'sowknow-sync' from anywhere."
fi

# Create convenience symlink names
ln -sf "$INSTALL_DIR/sowknow-auto-uploader.py" "$INSTALL_DIR/sowknow-auto-uploader"
ln -sf "$INSTALL_DIR/sowknow_sync.py" "$INSTALL_DIR/sowknow-sync"

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
echo ""
info "Configuration"
echo ""
echo "Choose authentication mode for the Auto-Uploader:"
echo "  1) API Key (recommended for Tailscale / no password stored)"
echo "  2) Email + Password (OAuth2 login)"
echo ""
read -rp "Select [1/2] (default: 1): " AUTH_MODE
AUTH_MODE="${AUTH_MODE:-1}"

SOWKNOW_URL="https://sowknow.gollamtech.com"
SOWKNOW_EMAIL=""
SOWKNOW_PASSWORD=""
SOWKNOW_BOT_API_KEY=""

if [[ "$AUTH_MODE" == "2" ]]; then
    read -rp "SOWKNOW email: " SOWKNOW_EMAIL
    read -rsp "SOWKNOW password: " SOWKNOW_PASSWORD
    echo ""
else
    read -rsp "SOWKNOW BOT_API_KEY (leave empty if not configured): " SOWKNOW_BOT_API_KEY
    echo ""
fi

# Email reporting (optional)
echo ""
read -rp "Send daily email reports? [y/N]: " SEND_REPORTS
SMTP_EMAIL=""
SMTP_PASSWORD=""
REPORT_RECIPIENT="smamadouster@gmail.com"
if [[ "${SEND_REPORTS,,}" == "y" ]]; then
    read -rp "Gmail address for sending reports: " SMTP_EMAIL
    read -rsp "Gmail App Password (not your login password): " SMTP_PASSWORD
    echo ""
    read -rp "Report recipient [$REPORT_RECIPIENT]: " RECIPIENT_INPUT
    REPORT_RECIPIENT="${RECIPIENT_INPUT:-$REPORT_RECIPIENT}"
fi

# ---------------------------------------------------------------------------
# Generate launchd plist
# ---------------------------------------------------------------------------
info "Configuring launchd service..."

# Build EnvironmentVariables section
ENV_XML=""
append_env() {
    local key="$1"
    local value="$2"
    if [[ -n "$value" ]]; then
        # Escape XML special characters
        value=$(echo "$value" | sed 's/&/\&amp;/g; s/</\&lt;/g; s/>/\&gt;/g; s/"/\&quot;/g; s/'"'"'/\&apos;/g')
        ENV_XML="${ENV_XML}        <key>${key}</key>
        <string>${value}</string>
"
    fi
}

append_env "SOWKNOW_URL" "$SOWKNOW_URL"
append_env "SOWKNOW_EMAIL" "$SOWKNOW_EMAIL"
append_env "SOWKNOW_PASSWORD" "$SOWKNOW_PASSWORD"
append_env "SOWKNOW_BOT_API_KEY" "$SOWKNOW_BOT_API_KEY"
append_env "SMTP_EMAIL" "$SMTP_EMAIL"
append_env "SMTP_PASSWORD" "$SMTP_PASSWORD"
append_env "REPORT_RECIPIENT" "$REPORT_RECIPIENT"

cat > "$PLIST_PATH" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.sowknow.autouploader</string>

    <key>ProgramArguments</key>
    <array>
        <string>/usr/bin/env</string>
        <string>python3</string>
        <string>$INSTALL_DIR/sowknow-auto-uploader.py</string>
    </array>

    <key>EnvironmentVariables</key>
    <dict>
$ENV_XML    </dict>

    <key>RunAtLoad</key>
    <true/>

    <key>KeepAlive</key>
    <true/>

    <key>StandardOutPath</key>
    <string>$LOGS_DIR/sowknow-auto-uploader.log</string>

    <key>StandardErrorPath</key>
    <string>$LOGS_DIR/sowknow-auto-uploader-error.log</string>

    <key>WorkingDirectory</key>
    <string>$HOME_DIR</string>
</dict>
</plist>
EOF

success "Created $PLIST_PATH"

# Unload old service if loaded
if launchctl list | grep -q "com.sowknow.autouploader"; then
    info "Stopping existing auto-uploader service..."
    launchctl unload "$PLIST_PATH" 2>/dev/null || true
fi

# Load new service
info "Starting auto-uploader service..."
launchctl load "$PLIST_PATH"
success "Auto-uploader service loaded"

# ---------------------------------------------------------------------------
# Sync Agent setup
# ---------------------------------------------------------------------------
echo ""
info "Sync Agent"
echo ""
read -rp "Set up SOWKNOW Sync Agent now? [Y/n]: " SETUP_SYNC
SETUP_SYNC="${SETUP_SYNC:-Y}"

if [[ "${SETUP_SYNC,,}" == "y" ]]; then
    "$INSTALL_DIR/sowknow_sync.py" --setup
fi

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
echo ""
echo "=========================================="
echo "  SOWKNOW macOS Upload Tools installed"
echo "=========================================="
echo ""
echo "Auto-Uploader:"
echo "  Script:     $INSTALL_DIR/sowknow-auto-uploader.py"
echo "  Plist:      $PLIST_PATH"
echo "  Logs:       $LOGS_DIR/sowknow-auto-uploader.log"
echo "  Error log:  $LOGS_DIR/sowknow-auto-uploader-error.log"
echo "  Folders:    ~/Desktop/Public  -> public"
echo "              ~/Desktop/Confidential -> confidential"
echo ""
echo "Sync Agent:"
echo "  Script:     $INSTALL_DIR/sowknow_sync.py"
echo "  Config:     ~/.sowknow/sync_config.json"
echo "  State:      ~/.sowknow/sync_state.json"
echo "  Log:        ~/.sowknow/sync_agent.log"
echo ""
echo "Commands:"
echo "  sowknow-auto-uploader --stop-service    # stop background uploader"
echo "  sowknow-auto-uploader --start-service   # start background uploader"
echo "  sowknow-auto-uploader --scan            # one-time scan"
echo "  sowknow-sync --setup                    # reconfigure sync agent"
echo "  sowknow-sync --sync                     # one-time sync"
echo "  sowknow-sync --watch                    # continuous sync"
echo ""

if [[ -n "$SHELL_RC" ]]; then
    echo "To use 'sowknow-sync' and 'sowknow-auto-uploader' from anywhere, run:"
    echo "  source $SHELL_RC"
    echo ""
fi

success "Installation complete!"
