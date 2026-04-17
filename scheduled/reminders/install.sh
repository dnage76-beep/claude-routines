#!/bin/bash
# Install the sheldon-reminders LaunchAgent. Runs twice daily (7:35 + 17:35).
set -eu

REPO="$(cd "$(dirname "$0")/../.." && pwd)"
HOME_DIR="$HOME"
UID_NUM="$(id -u)"
LABEL="com.nagel.sheldon-reminders"
TEMPLATE="$REPO/scheduled/reminders/com.nagel.sheldon-reminders.plist"
TARGET="$HOME_DIR/Library/LaunchAgents/${LABEL}.plist"

mkdir -p "$HOME_DIR/Library/Logs/sheldon-reminders"
mkdir -p "$HOME_DIR/Library/LaunchAgents"

# Ensure the Reminders list exists.
if [[ -x "$REPO/scheduled/reminders/setup_list.sh" ]]; then
    "$REPO/scheduled/reminders/setup_list.sh" >/dev/null 2>&1 || true
fi

sed -e "s|__HOME__|$HOME_DIR|g" -e "s|__REPO__|$REPO|g" "$TEMPLATE" > "$TARGET"

if ! plutil -lint "$TARGET" >/dev/null; then
    echo "ERROR: plist failed plutil -lint: $TARGET" >&2
    exit 1
fi

if ! launchctl bootstrap "gui/${UID_NUM}" "$TARGET" 2>/dev/null; then
    launchctl bootout "gui/${UID_NUM}/${LABEL}" 2>/dev/null || true
    launchctl bootstrap "gui/${UID_NUM}" "$TARGET"
fi

launchctl enable "gui/${UID_NUM}/${LABEL}"

echo "installed $LABEL (runs 7:35 AM + 5:35 PM daily)"
echo ""
echo "manual test:"
echo "  launchctl kickstart -k gui/${UID_NUM}/${LABEL}"
echo "  tail -f ~/Library/Logs/sheldon-reminders/*.log"
echo ""
echo "uninstall:  $REPO/scheduled/reminders/uninstall.sh"
