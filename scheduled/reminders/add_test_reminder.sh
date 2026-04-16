#!/usr/bin/env bash
# Manual test: drop a sample reminder into the "Sheldon Inbox" list.
# Useful for verifying the list exists, the Automation permission is granted,
# and the title/notes/due-date plumbing works end-to-end.
#
# Usage:
#   bash scheduled/reminders/add_test_reminder.sh
#   bash scheduled/reminders/add_test_reminder.sh "Custom title" "Custom notes"
#
# The reminder is set to be due 1 hour from now so you can see it appear at
# the top of the list right away.

set -euo pipefail

LIST_NAME="Sheldon Inbox"
TITLE="${1:-[TEST] Sheldon reminder wiring works}"
NOTES="${2:-Created by add_test_reminder.sh at $(date). Safe to delete.}"

# Due date: now + 1 hour, formatted for AppleScript "date" parser (M/D/YYYY H:MM:SS AM/PM)
DUE_DATE=$(date -v+1H "+%-m/%-d/%Y %-I:%M:%S %p")

osascript <<OSA >/dev/null
tell application "Reminders"
    tell list "$LIST_NAME"
        make new reminder with properties {name:"$TITLE", body:"$NOTES", due date:date "$DUE_DATE"}
    end tell
end tell
OSA

echo "Added reminder to '$LIST_NAME':" >&2
echo "  title: $TITLE" >&2
echo "  due:   $DUE_DATE" >&2
