"""
Cloud email triage — runs in GitHub Actions as a backup when the Mac is asleep.

Reuses extractor.run() with include_exchange=False (Mail.app is Mac-only) and
dry_run=True (Reminders.app is Mac-only). Sends the resulting digest to Derek
via Telegram bot — he already gets push notifications from @AmphibiousBot.

Secrets required (set via `gh secret set`):
  GMAIL_PERSONAL_TOKEN_B64    base64 of mcp-servers/gmail-multi/tokens/personal.json
  GMAIL_SECONDARY_TOKEN_B64   base64 of mcp-servers/gmail-multi/tokens/secondary.json
  TELEGRAM_BOT_TOKEN          bot token (same one used locally)
  TELEGRAM_CHAT_ID            numeric chat id (Derek's user id: 8739443748)
"""
from __future__ import annotations

import base64
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
TOKENS_DIR = REPO_ROOT / "mcp-servers" / "gmail-multi" / "tokens"


def _write_tokens() -> None:
    """Decode base64-encoded token secrets into the paths extractor.py expects."""
    TOKENS_DIR.mkdir(parents=True, exist_ok=True)
    for nick, env_var in [
        ("personal", "GMAIL_PERSONAL_TOKEN_B64"),
        ("secondary", "GMAIL_SECONDARY_TOKEN_B64"),
    ]:
        b64 = os.environ.get(env_var, "").strip()
        if not b64:
            print(f"WARN: {env_var} not set, skipping {nick}", file=sys.stderr)
            continue
        try:
            raw = base64.b64decode(b64)
        except Exception as exc:
            print(f"ERR: {env_var} not valid base64: {exc}", file=sys.stderr)
            continue
        path = TOKENS_DIR / f"{nick}.json"
        path.write_bytes(raw)
        path.chmod(0o600)


def _format_digest(planned: list[dict]) -> str:
    if not planned:
        return "📭 Cloud triage: nothing actionable in the last 24h."

    lines = [f"📬 *Cloud email triage* ({len(planned)} item{'s' if len(planned) != 1 else ''})\n"]
    for p in planned:
        cat = p.get("category", "misc")
        title = p.get("title", "(no title)")
        due = p.get("due")
        due_str = ""
        if due:
            # Trim timezone detail for readability
            due_str = f" — due {str(due)[:16].replace('T', ' ')}"
        src = p.get("source", "")
        src_str = f" [{src}]" if src else ""
        lines.append(f"• *{cat}*: {title}{due_str}{src_str}")
    lines.append("\n_Local triage will follow at 7:35 AM and add these to Apple Reminders._")
    return "\n".join(lines)


def _send_telegram(text: str) -> None:
    import urllib.request
    import urllib.parse
    import json as _json

    token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]

    # Telegram caps messages at 4096 chars; truncate generously.
    if len(text) > 3900:
        text = text[:3900] + "\n\n…(truncated)"

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    body = urllib.parse.urlencode({
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": "true",
    }).encode()
    req = urllib.request.Request(url, data=body, method="POST")
    with urllib.request.urlopen(req, timeout=15) as resp:
        resp_body = resp.read().decode()
        data = _json.loads(resp_body)
        if not data.get("ok"):
            raise RuntimeError(f"Telegram API error: {resp_body}")


def main() -> int:
    _write_tokens()

    # Import extractor AFTER tokens are in place; the extractor reads them
    # at service-build time which happens inside run().
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from extractor import run  # type: ignore

    try:
        planned = run(
            since_hours=24,
            dry_run=True,           # do NOT call AppleScript (we're on Linux)
            verbose=True,
            include_exchange=False, # Mail.app is macOS-only
        )
    except Exception as exc:
        # Still send a Telegram heads-up so Derek knows the cloud job ran & failed.
        try:
            _send_telegram(f"⚠️ Cloud email triage FAILED: `{type(exc).__name__}: {exc}`")
        except Exception:
            pass
        raise

    digest = _format_digest(planned)
    print(digest, file=sys.stderr)
    _send_telegram(digest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
