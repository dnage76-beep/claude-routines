#!/bin/bash
# install.sh - idempotent installer for the Sheldon Telegram LaunchAgent.

set -eu

REPO="/Users/Nagel/Documents/Code/claude-routines"
HOME_DIR="$HOME"
UID_NUM="$(id -u)"
LABEL="com.nagel.sheldon-telegram"
TEMPLATE="$REPO/sheldon-daemon/com.nagel.sheldon-telegram.plist"
TARGET="$HOME_DIR/Library/LaunchAgents/${LABEL}.plist"

mkdir -p "$HOME_DIR/Library/Logs/sheldon-telegram"
mkdir -p "$HOME_DIR/Library/LaunchAgents"

# Substitute placeholders and write the installed plist.
sed -e "s|__HOME__|$HOME_DIR|g" -e "s|__REPO__|$REPO|g" "$TEMPLATE" > "$TARGET"

# Validate before loading.
if ! plutil -lint "$TARGET" >/dev/null; then
    echo "ERROR: plist failed plutil -lint: $TARGET" >&2
    exit 1
fi

# Re-bootstrap pattern: bootout the old one if present, then bootstrap fresh.
if ! launchctl bootstrap "gui/${UID_NUM}" "$TARGET" 2>/dev/null; then
    launchctl bootout "gui/${UID_NUM}/${LABEL}" 2>/dev/null || true
    launchctl bootstrap "gui/${UID_NUM}" "$TARGET"
fi

launchctl enable "gui/${UID_NUM}/${LABEL}"
launchctl kickstart -k "gui/${UID_NUM}/${LABEL}"

echo ""
echo "Installed and started: $LABEL"
echo ""
echo "Verify:"
echo "  launchctl print gui/${UID_NUM}/${LABEL} | head -30"
echo "  tmux ls"
echo "  ./attach.sh              # see the live claude session"
echo "  tail -f ~/Library/Logs/sheldon-telegram/claude.log"
echo ""
echo "Stop (leaves agent installed):   ./stop.sh"
echo "Remove entirely:                 ./uninstall.sh"
