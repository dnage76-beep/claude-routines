#!/usr/bin/env bash
# Install the morning and evening triage launchd agents.
#
# Usage:   ./setup.sh
# Requires: mcp-servers/gmail-multi/.venv already built (Phase 1 SETUP.md).
#
# What this does:
#   1. Resolves absolute paths to runner.py and the gmail-multi venv python.
#   2. Renders the .plist templates with those paths.
#   3. Drops them into ~/Library/LaunchAgents/
#   4. launchctl loads them so they survive reboot.
#
# If Derek reboots: launchd re-reads ~/Library/LaunchAgents automatically. No
# action needed. The jobs run under his user session.

set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
PYTHON="$REPO/mcp-servers/gmail-multi/.venv/bin/python"
RUNNER="$HERE/runner.py"
LA_DIR="$HOME/Library/LaunchAgents"
LOG_DIR="$HOME/Library/Logs/sheldon-telegram-triage"

if [ ! -x "$PYTHON" ]; then
  echo "ERROR: gmail-multi venv python not found at $PYTHON"
  echo "Run Phase 1 setup first (see SETUP.md) — create the venv and install requirements."
  exit 1
fi

if [ ! -f "$RUNNER" ]; then
  echo "ERROR: runner.py missing at $RUNNER"
  exit 1
fi

mkdir -p "$LA_DIR" "$LOG_DIR"

# Check for credentials up front so we fail early with a clear message.
CRED_OK=0
if [ -n "${TELEGRAM_BOT_TOKEN:-}" ] && [ -n "${TELEGRAM_CHAT_ID:-}" ]; then CRED_OK=1; fi
if [ -f "$HERE/config.json" ]; then CRED_OK=1; fi
if [ -f "$HOME/.claude/channels/telegram/.env" ]; then CRED_OK=1; fi
if security find-generic-password -s sheldon-telegram-bot -w >/dev/null 2>&1; then CRED_OK=1; fi

if [ "$CRED_OK" = "0" ]; then
  echo "WARN: no Telegram credentials found in any of:"
  echo "  - \$TELEGRAM_BOT_TOKEN + \$TELEGRAM_CHAT_ID env"
  echo "  - $HERE/config.json"
  echo "  - $HOME/.claude/channels/telegram/.env"
  echo "  - macOS keychain entry 'sheldon-telegram-bot'"
  echo ""
  echo "The agents will load, but sends will fail until a token is in place."
  echo "Easiest fix: the Telegram plugin's .env already has your bot token,"
  echo "so if you have the plugin installed nothing else is needed."
fi

render_plist() {
  local src="$1"
  local dst="$2"
  sed \
    -e "s|__PYTHON__|$PYTHON|g" \
    -e "s|__RUNNER__|$RUNNER|g" \
    -e "s|__REPO__|$REPO|g" \
    -e "s|__HOME__|$HOME|g" \
    "$src" > "$dst"
}

install_agent() {
  local name="$1"   # morning | evening
  local label="com.sheldon.telegram-triage.$name"
  local src="$HERE/$name.plist"
  local dst="$LA_DIR/$label.plist"

  render_plist "$src" "$dst"

  # Unload if already loaded, then load fresh. bootout may error if not loaded,
  # so we ignore that with || true.
  launchctl bootout "gui/$UID/$label" 2>/dev/null || true
  launchctl bootstrap "gui/$UID" "$dst"
  launchctl enable "gui/$UID/$label"
  echo "loaded $label"
}

install_agent morning
install_agent evening

echo ""
echo "Done. To verify:"
echo "  launchctl list | grep telegram-triage"
echo ""
echo "To test-fire now without waiting:"
echo "  launchctl kickstart -k gui/\$UID/com.sheldon.telegram-triage.morning"
echo ""
echo "To dry-run manually (no Telegram send):"
echo "  $PYTHON $RUNNER morning --dry-run"
echo ""
echo "Logs: $LOG_DIR/"
