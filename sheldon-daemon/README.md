# sheldon-daemon

Keeps Sheldon's Telegram bot answering 24/7 while your Mac is awake.

## What it does

A macOS LaunchAgent supervises a `tmux` session named `sheldon-tg` running
`claude --dangerously-skip-permissions` in the foreground. The Anthropic
Telegram plugin auto-loads and polls Telegram from inside that claude
process. `caffeinate` keeps the Mac awake while the daemon runs. If claude
crashes, tmux dies, the supervisor script exits, and launchd respawns the
whole thing 30 seconds later.

## Setup

```
cd ~/Documents/Code/claude-routines/sheldon-daemon
./install.sh
```

That writes `~/Library/LaunchAgents/com.nagel.sheldon-telegram.plist`,
bootstraps it into your user launchd domain, and kicks it off immediately.

## Day-to-day

| Command          | What it does                                              |
| ---------------- | --------------------------------------------------------- |
| `./attach.sh`    | Attach your terminal to the live claude session. Detach with `Ctrl-b` then `d`. |
| `./stop.sh`      | Kill the tmux session + signal the agent. Agent stays installed (will NOT auto-restart until next login or kickstart). |
| `./uninstall.sh` | Fully remove the LaunchAgent and kill the session. |
| `tail -f ~/Library/Logs/sheldon-telegram/claude.log` | Watch Sheldon's live output. |
| `tail -f ~/Library/Logs/sheldon-telegram/daemon.err.log` | launchd-level errors. |

## Known gotchas

- **Mac sleep:** `caffeinate -dimsu` keeps the Mac awake while the daemon
  is running. If you force sleep manually (close the lid on battery, etc.)
  the bot goes deaf until wake. System-sleep suppression via `-s` only
  works on AC power.
- **409 Conflict from Telegram:** only one poller can hold the bot token's
  long-poll slot. Don't run `claude` in another terminal while the daemon
  is up -- or run `./stop.sh` first, do your thing, then `launchctl
  kickstart -k gui/$(id -u)/com.nagel.sheldon-telegram` when done.
- **Log rotation:** launchd doesn't rotate. Truncate any time:
  `: > ~/Library/Logs/sheldon-telegram/claude.log`
- **First run of the day:** give it ~10 seconds to boot the plugin before
  texting the bot.
