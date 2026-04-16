# Scheduled Telegram triage

Fires twice a day (7:30am + 7:00pm America/New_York) and pushes a short
Urgent / This week / FYI digest of the last ~12 hours of mail across:

- `personal`  -- dnage76@gmail.com  (Gmail API, uses Phase-1 tokens)
- `secondary` -- dereknagel05@gmail.com (Gmail API, uses Phase-1 tokens)
- `gmu`       -- dnagel@gmu.edu (Apple Mail's Envelope Index SQLite + .emlx)

Delivery goes straight to the Telegram Bot API over HTTPS -- no Claude Code
session needs to be running, no terminal open. The job lives in `launchd` so
it survives reboot and runs whenever the Mac is awake at the scheduled time.

## How it plugs together

```
launchd
  -> gmail-multi/.venv/bin/python runner.py morning|evening
       -> Gmail API (personal, secondary)
       -> ~/Library/Mail/V10/... (gmu)
       -> ranks into Urgent / This week / FYI
       -> POST https://api.telegram.org/bot<TOKEN>/sendMessage
```

## Install

Phase 1 must already be done (gmail-multi venv built, tokens authorized).

```bash
cd scheduled/telegram-triage
./setup.sh
```

That renders the two `.plist` templates with the correct absolute paths and
loads them. Verify:

```bash
launchctl list | grep telegram-triage
```

You should see both labels. To test-fire morning immediately:

```bash
launchctl kickstart -k gui/$UID/com.sheldon.telegram-triage.morning
```

You can also run the script directly:

```bash
../../mcp-servers/gmail-multi/.venv/bin/python runner.py morning --dry-run
```

`--dry-run` prints the message and skips the Telegram send.

## Uninstall

```bash
./uninstall.sh
```

Removes the launchd agents and their plist files. Logs and state stay in
`~/Library/Logs/sheldon-telegram-triage/` and `~/.sheldon/telegram-triage/`.

## Credentials

The runner looks for the Telegram bot token and chat_id in this order, and
stops at the first one that works:

1. `$TELEGRAM_BOT_TOKEN` + `$TELEGRAM_CHAT_ID` env vars
2. `scheduled/telegram-triage/config.json` (gitignored) -- copy from
   `config.example.json` and fill in
3. **`~/.claude/channels/telegram/.env`** -- the file the Telegram plugin
   already writes when you run `/telegram:configure`. The chat_id is pulled
   from the first entry of the plugin's `access.json` allowlist.
4. macOS Keychain:
   ```bash
   security add-generic-password -a $USER -s sheldon-telegram-bot  -w '<TOKEN>'
   security add-generic-password -a $USER -s sheldon-telegram-chat -w '<CHAT_ID>'
   ```

**If you already use the Telegram Claude plugin**, option 3 means you don't
have to paste the token anywhere new -- the runner just reuses the plugin's
stored credentials.

## Timing decisions

- **Morning 7:30 ET** -- Derek's typically at practice / class by 8, 7:30
  gives him ~15 min over coffee to act on urgent items. Early enough that the
  digest still covers last-night emails.
- **Evening 7:00 ET** -- late enough that most workday mail is in, early
  enough to not collide with Jillian being over on weekends.
- **Missed runs** -- launchd will run the job at the next boot/wake if the
  scheduled time was missed while the Mac was off or asleep
  (`AbandonProcessGroup` + default launchd semantics).

## Message format

Matches `routines/daily-inbox-triage.md`:

```
Sheldon morning triage

Urgent
- [personal] From — Subject  [personal:19abc123]

This week
- [gmu] From — Subject  [gmu:45678]

FYI
- [secondary] From — Subject  [secondary:19def456]

Reply with "draft reply to [ref]" and the next Sheldon session will pick it up.
```

Caps: 3 per bucket, 7 total. Ranking prefers known senders (Derek's advisor,
professors, Northrop recruiter, family, housing manager), penalizes obvious
newsletter/auto-reply patterns.

## Threaded replies

Each item carries a `[source:message_id]` footer. When Derek replies on
Telegram with "draft reply to personal:19abc123", the next Claude Code
session can look at `~/.sheldon/telegram-triage/last-push.json` to resolve
the ref into a full sender/subject/body and then call `gmail_read` against
the correct account nickname.

The `last-push.json` is written every time the runner fires, regardless of
whether the send succeeded.

## Files

| Path | Purpose |
|------|---------|
| `runner.py` | Fetches mail, ranks, sends to Telegram |
| `morning.plist` / `evening.plist` | launchd templates with `__PLACEHOLDERS__` |
| `setup.sh` | Renders templates + `launchctl bootstrap` |
| `uninstall.sh` | `launchctl bootout` + remove files |
| `config.example.json` | Template for credentials override |
| `.gitignore` | Never commit `config.json` |

## Logs

- `~/Library/Logs/sheldon-telegram-triage/runner.log` -- runner's own log
- `~/Library/Logs/sheldon-telegram-triage/morning.out.log` -- launchd stdout
- `~/Library/Logs/sheldon-telegram-triage/morning.err.log` -- launchd stderr
- (evening counterparts exist too)

Grep `telegram send ok=` to see send success/failure per run.

## Troubleshooting

**"No token for personal"**: you haven't finished Phase 1's Gmail OAuth. Run
`python auth.py personal` (and `secondary`) inside `mcp-servers/gmail-multi`.

**"exchange inbox mailbox not found"**: Apple Mail hasn't cached GMU mail
yet, or the account UUID in `runner.py` (`EXCHANGE_ACCOUNT_UUID`) doesn't
match your machine. Check `mcp-servers/mail-exchange/server.py` -- the UUID
is identical in both places.

**SSL CERTIFICATE_VERIFY_FAILED**: the runner already uses `certifi` from
the gmail-multi venv. If you see this, check that `pip install certifi`
ran during the gmail-multi venv setup (it's a google-api-python-client
transitive dependency).

**Silent failure**: check `~/Library/Logs/sheldon-telegram-triage/runner.log`.
Every run logs its timing and whether Telegram accepted the message.

**Full Disk Access**: the GMU Exchange source reads
`~/Library/Mail/V10/MailData/Envelope Index`. The Python interpreter running
under launchd needs Full Disk Access. If GMU items don't show up but Gmail
does, grant FDA to `Terminal.app` (when testing) and to `/usr/libexec/sshd`
or the specific Python binary (for launchd). Usually easiest: add the
`python3.14` binary at `mcp-servers/gmail-multi/.venv/bin/python3.14` to
System Settings -> Privacy & Security -> Full Disk Access.
