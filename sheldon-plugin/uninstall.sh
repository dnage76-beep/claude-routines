#!/bin/zsh
# Revert to upstream Telegram plugin + remove Sheldon skill.
set -eu

UPSTREAM="$HOME/.claude/plugins/cache/claude-plugins-official/telegram/0.0.6"
SKILLS_DST="$HOME/.claude/skills/sheldon-behavior"

if [[ -f "$UPSTREAM/server.ts.upstream" ]]; then
  mv "$UPSTREAM/server.ts.upstream" "$UPSTREAM/server.ts"
  echo "restored upstream server.ts"
fi

if [[ -L "$SKILLS_DST" || -d "$SKILLS_DST" ]]; then
  rm -rf "$SKILLS_DST"
  echo "removed sheldon-behavior skill"
fi

echo "done. restart claude to pick up changes."
