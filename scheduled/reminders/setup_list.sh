#!/usr/bin/env bash
# Create the "Sheldon Inbox" list in Apple Reminders if it doesn't already exist.
# Idempotent: re-running is a no-op.
#
# Usage:
#   bash scheduled/reminders/setup_list.sh
#
# Requires:
#   - macOS with Reminders.app
#   - Terminal granted Automation permission for Reminders (first run will prompt)

set -euo pipefail

LIST_NAME="Sheldon Inbox"

exists=$(osascript <<OSA
tell application "Reminders"
    set listNames to name of lists
    if listNames contains "$LIST_NAME" then
        return "yes"
    else
        return "no"
    end if
end tell
OSA
)

if [ "$exists" = "yes" ]; then
    echo "List '$LIST_NAME' already exists. Nothing to do." >&2
    exit 0
fi

osascript <<OSA >/dev/null
tell application "Reminders"
    make new list with properties {name:"$LIST_NAME"}
end tell
OSA

echo "Created list '$LIST_NAME'." >&2
