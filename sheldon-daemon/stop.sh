#!/bin/bash
# stop.sh - kill the running tmux session and signal the LaunchAgent.
# Does NOT unload the LaunchAgent; launchd will respect the exit because
# KeepAlive uses SuccessfulExit=false. For full removal, use uninstall.sh.

set -u

SESSION="sheldon-tg"
UID_NUM="$(id -u)"

tmux kill-session -t "$SESSION" 2>/dev/null || true
launchctl kill TERM "gui/${UID_NUM}/com.nagel.sheldon-telegram" 2>/dev/null || true

echo "Stopped session $SESSION and signaled LaunchAgent."
echo "(LaunchAgent is still installed. Run ./uninstall.sh to remove it.)"
