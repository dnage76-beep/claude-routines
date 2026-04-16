#!/usr/bin/env bash
# Remove the morning and evening triage launchd agents.

set -euo pipefail

LA_DIR="$HOME/Library/LaunchAgents"

for name in morning evening; do
  label="com.sheldon.telegram-triage.$name"
  dst="$LA_DIR/$label.plist"
  launchctl bootout "gui/$UID/$label" 2>/dev/null || true
  if [ -f "$dst" ]; then
    rm "$dst"
    echo "removed $dst"
  else
    echo "no agent at $dst"
  fi
done

echo ""
echo "Logs and state in ~/Library/Logs/sheldon-telegram-triage/ and ~/.sheldon/telegram-triage/ left intact."
echo "Delete manually if you want a clean slate."
