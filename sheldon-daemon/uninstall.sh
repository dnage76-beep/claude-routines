#!/bin/bash
# uninstall.sh - remove the Sheldon Telegram LaunchAgent entirely.

set -u

UID_NUM="$(id -u)"
LABEL="com.nagel.sheldon-telegram"
TARGET="$HOME/Library/LaunchAgents/${LABEL}.plist"

launchctl bootout "gui/${UID_NUM}/${LABEL}" 2>/dev/null || true
rm -f "$TARGET"
tmux kill-session -t sheldon-tg 2>/dev/null || true

echo "Uninstalled $LABEL and killed any running tmux session."
echo "Logs at ~/Library/Logs/sheldon-telegram/ were left in place."
