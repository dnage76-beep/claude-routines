# Multi-account Gmail setup

Wires three Gmail accounts (personal, secondary, GMU) into Claude Code via a
local MCP server.

## One-time: Google Cloud project

1. Go to https://console.cloud.google.com/ and create a new project
   (name it e.g. `claude-routines`).
2. Enable the **Gmail API**: APIs & Services -> Library -> search "Gmail API" -> Enable.
3. Configure the **OAuth consent screen**:
   - User type: **External**
   - App name: `claude-routines`
   - User support email + developer email: your own
   - Scopes: add `.../auth/gmail.readonly`
   - **Test users**: add all three addresses
     - `dnage76@gmail.com`
     - `dereknagel05@gmail.com`
     - `dnagl@gmu.edu`
4. Create **OAuth client credentials**:
   - Credentials -> Create Credentials -> OAuth client ID
   - Application type: **Desktop app**
   - Download JSON -> save as `mcp-servers/gmail-multi/credentials.json`

## One-time: local environment

```bash
cd mcp-servers/gmail-multi
cp config.example.json config.json
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Authorize each account (run three times)

```bash
python auth.py personal     # sign in as dnage76@gmail.com
python auth.py secondary    # sign in as dereknagel05@gmail.com
python auth.py gmu          # sign in as dnagl@gmu.edu
```

Each run opens a browser, you pick the matching account, tokens land in
`tokens/<nickname>.json`. Refresh happens automatically after that.

## Verify

Restart Claude Code in this repo. Ask:

> list my gmail accounts

Claude should call `gmail_list_accounts` and show all three as
`authorized: true`.

## Files and secrets

Gitignored (never committed): `config.json`, `credentials.json`, `tokens/`.
Only `config.example.json` and the server code are tracked.
