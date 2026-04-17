#!/bin/bash
# start.sh - launchd-supervised entrypoint for the Sheldon Telegram daemon.
#
# IMPORTANT: launchd supervises THIS script. If this script exits, launchd
# (with KeepAlive.Crashed=true + ThrottleInterval=30) will respawn it.
#
# WHY WE USE `tmux new-session -d` (detached) AND THEN BLOCK:
#   tmux is a client/server model. Any `tmux new-session` call (attached or
#   detached) causes the tmux SERVER to daemonize itself into the background.
#   If we just ran `tmux new-session -s foo 'cmd'` (no -d) under launchd,
#   there is no TTY to attach the client to, and even if there were, the
#   server still forks away -- the foreground client exits as soon as the
#   session is created, returning 0, causing launchd to respawn us instantly.
#
#   So: we create the session detached, then BLOCK this script in a polling
#   loop on `tmux has-session`. While the session exists, this script stays
#   alive, launchd stays happy, and the claude process runs inside the tmux
#   pane where Derek can `./attach.sh` to see it. When the session dies
#   (claude crashed out, Derek killed it, etc.), this script exits, and
#   launchd waits ThrottleInterval=30s, then respawns us. Clean.

set -u

SESSION="sheldon-tg"
REPO="/Users/Nagel/Documents/Code/claude-routines"
LOG_DIR="$HOME/Library/Logs/sheldon-telegram"

export HOME="/Users/Nagel"
export PATH="/opt/homebrew/bin:/usr/local/bin:$HOME/.local/bin:/usr/bin:/bin"
export LANG="en_US.UTF-8"

mkdir -p "$LOG_DIR"

# Idempotency: if session already exists, attach ourselves to its lifecycle
# and exit when it dies. Prevents duplicate sessions if launchd double-fires.
if tmux has-session -t "$SESSION" 2>/dev/null; then
    echo "[$(date)] session $SESSION already exists; tailing its lifecycle" >> "$LOG_DIR/start.log"
    while tmux has-session -t "$SESSION" 2>/dev/null; do
        sleep 10
    done
    exit 0
fi

# Belt-and-suspenders: clear any stray poller from a crashed prior claude.
# The plugin has its own stale-check, but orphans can still block :8788 or
# hold the Telegram long-poll slot (409 Conflict).
pkill -f "bun.*telegram/0.0.6/server.ts" 2>/dev/null || true
sleep 1

cd "$REPO" || exit 1

echo "[$(date)] starting session $SESSION" >> "$LOG_DIR/start.log"

# caffeinate flags:
#   -d display awake, -i idle-sleep off, -m disk awake,
#   -s system-sleep off (only effective on AC), -u user activity assertion.
# This keeps the Mac awake while claude runs, which is what Derek wants.
tmux new-session -d -s "$SESSION" -x 220 -y 60 \
    "caffeinate -dimsu claude --dangerously-skip-permissions --permission-mode bypassPermissions 2>&1 | tee -a '$LOG_DIR/claude.log'"

# Block until the session goes away, so launchd sees us as alive.
while tmux has-session -t "$SESSION" 2>/dev/null; do
    sleep 10
done

echo "[$(date)] session $SESSION ended; exiting for launchd respawn" >> "$LOG_DIR/start.log"
exit 0
