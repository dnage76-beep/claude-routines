# Sheldon Console

Terminal dashboard for checking on the Sheldon Telegram daemon.

## Run

```bash
./sheldon-console/sheldon
```

Or put it on your PATH:

```bash
ln -s "$PWD/sheldon-console/sheldon" ~/.local/bin/sheldon
# then just: sheldon
```

## What it shows

- Logo banner on launch
- Live status: LaunchAgent, tmux session, claude process, Telegram poller, bot username, allowlist count, daemon uptime
- Last 10 lines of `~/Library/Logs/sheldon-telegram/claude.log`
- Command menu

## Keys

| Key | Action |
|-----|--------|
| `a` | Attach to tmux (Ctrl-b then d to detach) |
| `r` | Restart daemon (launchctl kickstart -k) |
| `s` | Start daemon |
| `x` | Stop daemon + kill tmux session |
| `l` | Live tail the claude log (Ctrl-C to return) |
| `v` | Open the Telegram vault log in Obsidian |
| `t` | Send `/triage` to the live tmux session |
| `b` | Ping Telegram (getMe + getWebhookInfo) to verify bot is reachable |
| `q` | Quit |

## Requires

- `python3` with `rich` (auto-installs if missing)
- `tmux`
- Sheldon daemon installed (see `../sheldon-daemon/`)
