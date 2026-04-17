#!/bin/bash
# Install the sheldon-reminders LaunchAgent. Runs twice daily (7:35 + 17:35).
#
# Why a .app bundle wrapper: macOS TCC needs a stable code identity to persist
# Full Disk Access grants. Bare shell scripts get rehashed on every edit and
# lose their grant. A signed .app bundle with a bundle id stays stable across
# extractor.py edits.
#
# NOTE: Mail.app envelope DB reads are blocked under launchd regardless of FDA
# (Apple hardened ~/Library/Mail/V10 beyond normal FDA scope). Exchange errors
# in the launchd run are harmless — use /reminders in Telegram for full triage
# (runs under Claude.app which has working FDA).
set -eu

REPO="$(cd "$(dirname "$0")/../.." && pwd)"
HOME_DIR="$HOME"
UID_NUM="$(id -u)"
LABEL="com.nagel.sheldon-reminders"
TEMPLATE="$REPO/scheduled/reminders/com.nagel.sheldon-reminders.plist"
TARGET="$HOME_DIR/Library/LaunchAgents/${LABEL}.plist"

mkdir -p "$HOME_DIR/Library/Logs/sheldon-reminders"
mkdir -p "$HOME_DIR/Library/LaunchAgents"

if [[ -x "$REPO/scheduled/reminders/setup_list.sh" ]]; then
    "$REPO/scheduled/reminders/setup_list.sh" >/dev/null 2>&1 || true
fi

# --- build .app bundle wrapper ----------------------------------------------
BUNDLE="$HOME_DIR/Library/Scripts/sheldon/SheldonReminders.app"
mkdir -p "$BUNDLE/Contents/MacOS"

cat > "$BUNDLE/Contents/Info.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleExecutable</key>      <string>SheldonReminders</string>
    <key>CFBundleIdentifier</key>      <string>com.nagel.sheldon-reminders</string>
    <key>CFBundleName</key>            <string>SheldonReminders</string>
    <key>CFBundlePackageType</key>     <string>APPL</string>
    <key>CFBundleVersion</key>         <string>1.0</string>
    <key>LSUIElement</key>             <true/>
    <key>LSBackgroundOnly</key>        <true/>
</dict>
</plist>
EOF

cat > "$BUNDLE/Contents/MacOS/SheldonReminders" <<'EOF'
#!/bin/bash
set -eu
REPO="$HOME/Documents/Code/claude-routines"
cd "$REPO"
exec "$REPO/mcp-servers/gmail-multi/.venv/bin/python" \
     "$REPO/scheduled/reminders/extractor.py" --since-hours 24
EOF
chmod +x "$BUNDLE/Contents/MacOS/SheldonReminders"

# Ad-hoc code-sign for stable TCC identity.
codesign --force --deep --sign - "$BUNDLE" 2>/dev/null || true

# --- launchd plist -----------------------------------------------------------
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
echo "Gmail triage works in launchd. For GMU Exchange triage, use /reminders in Telegram"
echo "or run manually from Terminal:"
echo "  $REPO/mcp-servers/gmail-multi/.venv/bin/python $REPO/scheduled/reminders/extractor.py"
echo ""
echo "manual test:  launchctl kickstart -k gui/${UID_NUM}/${LABEL}"
echo "tail logs:    tail -f ~/Library/Logs/sheldon-reminders/*.log"
echo "uninstall:    $REPO/scheduled/reminders/uninstall.sh"
