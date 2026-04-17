#!/bin/bash
set -eu
UID_NUM="$(id -u)"
LABEL="com.nagel.sheldon-reminders"
launchctl bootout "gui/${UID_NUM}/${LABEL}" 2>/dev/null || true
rm -f "$HOME/Library/LaunchAgents/${LABEL}.plist"
echo "uninstalled $LABEL"
