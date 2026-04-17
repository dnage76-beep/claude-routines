# Installing the Sheldon Telegram fork

This is a fork of the Anthropic-official `telegram` plugin (0.0.6) with four Sheldon-specific additions: persistent typing indicator, `reply_with_buttons` MCP tool, expanded slash-command menu with `/stop`, and optional Whisper voice transcription.

Two install options. Pick one.

## Option A — Shadow upstream (simplest)

Replace the cached upstream plugin in place. Every `claude` launch will pick up the fork.

```bash
# Back up the upstream copy first.
cp -R ~/.claude/plugins/cache/claude-plugins-official/telegram/0.0.6 \
      ~/.claude/plugins/cache/claude-plugins-official/telegram/0.0.6.upstream-backup

# Sync the fork over the cached plugin. Use rsync so node_modules (already
# correct) stays put; only the edited files get replaced.
rsync -a --delete \
  /Users/Nagel/Documents/Code/claude-routines/sheldon-plugin/telegram/ \
  ~/.claude/plugins/cache/claude-plugins-official/telegram/0.0.6/
```

Restart any running Claude session. When it next spawns the Telegram MCP, the forked `server.ts` runs.

Trade-off: any `claude` plugin-cache refresh or reinstall of the upstream plugin will clobber the fork. Re-run the rsync when that happens. Keep the fork versioned here so it's easy.

### Updating

Pull the fork's latest (git pull in `~/Documents/Code/claude-routines`) and re-rsync.

## Option B — Separate plugin via plugin.json

Install the fork as its own plugin so it coexists with upstream (though you'd want to disable upstream to avoid two bots polling the same token).

1. Symlink the fork into the plugins directory:
   ```bash
   mkdir -p ~/.claude/plugins/local
   ln -sfn /Users/Nagel/Documents/Code/claude-routines/sheldon-plugin/telegram \
          ~/.claude/plugins/local/telegram-sheldon
   ```
2. Register it in your plugin marketplace or via `~/.claude/settings.json` / `.claude/settings.local.json` depending on your setup. The fork's `.claude-plugin/plugin.json` already has `"name": "telegram"` and `"version": "0.0.6-sheldon"`, so disable the upstream copy first:
   ```bash
   mv ~/.claude/plugins/cache/claude-plugins-official/telegram/0.0.6 \
      ~/.claude/plugins/cache/claude-plugins-official/telegram/0.0.6.disabled
   ```
3. If you want a distinct plugin name (so both can coexist in metadata), edit the fork's `.claude-plugin/plugin.json` to `"name": "telegram-sheldon"` before installing. You'll still only run one bot — two pollers on the same token hit 409 Conflict.

## Enabling Whisper transcription (optional)

The voice-transcription feature is off by default. To enable:

```bash
pip3 install openai-whisper --break-system-packages
# Then in your shell / launchd env for the claude process:
export SHELDON_WHISPER=1
# Optional — default is "base". Other values: "tiny", "small", "medium", "large".
export SHELDON_WHISPER_MODEL=base
```

Without `SHELDON_WHISPER=1` set, voice messages behave exactly as upstream (no transcription, passed to Claude as an attachment). If Whisper is enabled but fails at runtime (missing package, python3 not in PATH, etc.), the plugin falls back to upstream behavior silently; check the MCP server's stderr for the one-line error.

## How `/stop` works

At startup the server writes its parent PID (the `claude` process that spawned it) to `~/.claude/channels/telegram/claude.pid`. When Derek sends `/stop`, the plugin:

1. Reads that file, checks the PID is alive (`kill -0`), sends it `SIGINT` (Ctrl-C equivalent).
2. If that fails, tries `tmux send-keys -t sheldon-tg C-c` as a fallback.
3. If both fail, replies telling Derek to check `claude.pid`.

This is best-effort. If Claude is mid-tool-call, SIGINT may not land cleanly — Claude 2.1.111 has no public API for the plugin to cancel an in-flight turn. Revisit this when upstream adds one.

## Verifying the install

After installing, DM the bot `/help` — you should see "I'm Sheldon. Text me for anything…". Send any real question and confirm the typing indicator stays lit for longer than ~5s while Claude works.
