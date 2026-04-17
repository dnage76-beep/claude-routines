# Sheldon fork diff — upstream telegram plugin 0.0.6

Every change in `telegram/server.ts` is marked with `// SHELDON:` so future upstream merges are straightforward. Line numbers below are approximate (original → new) to help locate the edit sites.

## package.json

- `version`: `"0.0.1"` → `"0.0.6-sheldon"`

## .claude-plugin/plugin.json

- `version`: `"0.0.6"` → `"0.0.6-sheldon"`

## server.ts

### 1. Imports (orig ~22, new ~22-26)

Added `spawn, spawnSync` from `child_process` for `/stop` and whisper transcription.

### 2. Parent-PID capture + persistent typing registry (new block, orig ~70, new ~73-101)

Inserted right after `writeFileSync(PID_FILE, …)`:

- Writes `process.ppid` to `~/.claude/channels/telegram/claude.pid` so `/stop` can SIGINT the parent `claude` process.
- Adds `typingTimers: Map<chatId, {interval, safety}>` plus `startTyping(chat_id)` and `stopTyping(chat_id)` helpers. `startTyping` fires `sendChatAction('typing')` immediately, re-fires every 4000ms, and hard-clears after 120000ms as a safety net.

### 3. reply_with_buttons tool registration (orig ~486 ListTools; new ~518-550)

Added a new tool descriptor directly above `edit_message` in the `ListToolsRequestSchema` response. Schema: `{chat_id, text, buttons: Array<Array<{label, value}>>, reply_to?}`.

### 4. reply / edit_message handlers — stop typing indicator (orig ~574, ~613)

- In `case 'reply':` — after sending, call `stopTyping(chat_id)` before `return`.
- In `case 'edit_message':` — after editing, call `stopTyping(args.chat_id as string)` before `return`.

### 5. reply_with_buttons handler (orig ~577 just before 'react'; new ~609-639)

New `case 'reply_with_buttons':`. Validates limits (≤3 rows, ≤8 total buttons, ≤40-char label, ≤56-char value — callback_data is 64-byte capped, `sheldon:` prefix eats 8). Calls `bot.api.sendMessage` with a grammy `InlineKeyboard` and threads under `reply_to` if provided. Calls `stopTyping` on send.

### 6. sheldon callback handler (orig ~725 just before perm handler; new ~757-793)

New `bot.callbackQuery(/^sheldon:/, …)` registered BEFORE the permission `bot.on('callback_query:data', …)`. Auths the tapper (DM must be in `allowFrom`; group must be a registered group), answers the callback with "✓", and emits `notifications/claude/channel` with `content: "[button: <value>]"` and `meta.button_callback: <value>`. Kicks `startTyping` so the user sees the indicator while Claude processes. Does NOT delete or edit the original message — Claude decides.

### 7. Slash-command routing + /stop + /help override (orig ~697 between 'help' and 'status'; new ~816-930)

- Replaced upstream `bot.command('help', …)` body with a Sheldon-specific reply ("I'm Sheldon… Commands: /brief /triage /calendar /texts /vault /stop").
- Added `sheldonCommandPrompt(cmd, rest)` to map each command to a fuller natural-language prompt.
- Added `handleSheldonCommand(ctx, cmd, rest)` — runs `gate()`, handles `pair`/`drop` the same way as `handleInbound`, then kicks `startTyping` and emits a `notifications/claude/channel` with the expanded prompt and `meta.sheldon_command: <cmd>`.
- Registered `bot.command('brief'|'triage'|'calendar'|'texts'|'vault', …)` using the new helper.
- Registered `bot.command('stop', …)` — acks "⏹ Stopping current task…", then best-effort: (A) SIGINT the pid recorded at boot if alive; (B) fall back to `tmux send-keys -t sheldon-tg C-c`. If neither works, tells the user.

### 8. handleInbound typing indicator (orig ~939-940; replaced)

Replaced the one-shot `void bot.api.sendChatAction(chat_id, 'typing')` with `startTyping(chat_id)`.

### 9. Voice transcription (orig ~824; new ~1078-1153)

- Rewrote `bot.on('message:voice', …)` to optionally download the .ogg, run Whisper, and prefix the inbound `content` with `"[voice transcript] <text>"`.
- Gated on `SHELDON_WHISPER=1`. Wrapped in try/catch — any failure (missing python, missing whisper package, download error) falls back to the original behavior (passes voice as attachment).
- Added `transcribeWhisper(path)` helper: shells out to `python3 -c "import whisper; …"`, 90s timeout, returns undefined on any failure. Model is `base` by default, overridable via `SHELDON_WHISPER_MODEL`.

### 10. setMyCommands menu (orig ~1001; new ~1273-1284)

Replaced the upstream three-command list (`start`, `help`, `status`) with the seven Sheldon commands (`brief`, `triage`, `calendar`, `texts`, `vault`, `stop`, `help`). Still scoped to `all_private_chats`.

## Verification

Ran in the forked directory:

```
bun install
bun build --target=node server.ts   # succeeded
bunx tsc --noEmit --lib es2022,dom --target es2022 --module esnext \
  --moduleResolution bundler --skipLibCheck --types node server.ts   # zero errors
```

(The typecheck needs `@types/node` installed transiently; this was not persisted into the fork's package.json.)
