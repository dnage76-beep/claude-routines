#!/bin/zsh
# Activate the Sheldon fork of the Telegram plugin + install the behavior skill.
# Idempotent. Run: ./sheldon-plugin/install.sh

set -eu

REPO="$(cd "$(dirname "$0")/.." && pwd)"
FORK="$REPO/sheldon-plugin/telegram"
UPSTREAM="$HOME/.claude/plugins/cache/claude-plugins-official/telegram/0.0.6"
SKILLS_SRC="$REPO/sheldon-plugin/skills/sheldon-behavior"
SKILLS_DST="$HOME/.claude/skills/sheldon-behavior"

if [[ ! -d "$UPSTREAM" ]]; then
  echo "error: upstream Telegram plugin not found at $UPSTREAM"
  echo "install it first: claude plugin install telegram@claude-plugins-official"
  exit 1
fi

# 1. Back up upstream server.ts (once)
if [[ ! -f "$UPSTREAM/server.ts.upstream" ]]; then
  cp "$UPSTREAM/server.ts" "$UPSTREAM/server.ts.upstream"
  echo "backed up upstream server.ts -> server.ts.upstream"
fi

# 2. Shadow upstream with our forked server.ts
cp "$FORK/server.ts" "$UPSTREAM/server.ts"
echo "installed forked server.ts into $UPSTREAM"

# 3. Ensure node_modules exist in the upstream dir so `bun start` still works.
# (The plugin's package.json already runs `bun install --no-summary` on start.)

# 4. Install sheldon-behavior skill
mkdir -p "$HOME/.claude/skills"
if [[ -L "$SKILLS_DST" || -d "$SKILLS_DST" ]]; then
  rm -rf "$SKILLS_DST"
fi
ln -s "$SKILLS_SRC" "$SKILLS_DST"
echo "linked sheldon-behavior skill -> $SKILLS_DST"

echo
echo "done. next steps:"
echo "  1. restart any running claude session so the new plugin + skill load"
echo "  2. install the always-on daemon:  $REPO/sheldon-daemon/install.sh"
echo "  3. (optional) enable voice transcription: echo 'SHELDON_WHISPER=1' >> ~/.claude/channels/telegram/.env"
echo "     and:  pip3 install openai-whisper --break-system-packages"
