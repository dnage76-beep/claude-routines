"""Read GMU Exchange mail from Apple Mail.app's local cache.

Exposes search/read tools for the Exchange-backed GMU account (dnagel@gmu.edu)
via Mail.app's Envelope Index SQLite database + .emlx message files on disk.

Requires Full Disk Access granted to the process running this server.
"""
from __future__ import annotations

import email
import email.policy
import re
import shutil
import sqlite3
import tempfile
import urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

MAIL_ROOT = Path.home() / "Library" / "Mail" / "V10"
ENVELOPE_DB = MAIL_ROOT / "MailData" / "Envelope Index"

EXCHANGE_ACCOUNT_UUID = "00EC10D3-DDC8-4213-93CE-8906B6CB949B"

mcp = FastMCP("mail-exchange")


def _copy_db() -> str:
    """Copy the live Envelope Index to a temp file so we don't fight Mail.app locks."""
    tmp = Path(tempfile.gettempdir()) / "envelope_copy.sqlite"
    shutil.copy(ENVELOPE_DB, tmp)
    for suffix in ("-shm", "-wal"):
        src = Path(f"{ENVELOPE_DB}{suffix}")
        if src.exists():
            shutil.copy(src, f"{tmp}{suffix}")
    return str(tmp)


def _connect() -> sqlite3.Connection:
    db_path = _copy_db()
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _fmt_date(ts: int | None) -> str:
    if not ts:
        return ""
    return datetime.fromtimestamp(ts, tz=timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M")


def _mailbox_id(conn: sqlite3.Connection, folder: str) -> int | None:
    """Get the mailbox ROWID for the Exchange account's named folder."""
    encoded = urllib.parse.quote(folder, safe="/")
    url = f"ews://{EXCHANGE_ACCOUNT_UUID}/{encoded}"
    row = conn.execute("SELECT ROWID FROM mailboxes WHERE url = ?", (url,)).fetchone()
    return row["ROWID"] if row else None


def _find_emlx(message_rowid: int, remote_id: str | None) -> Path | None:
    """Locate the .emlx file for a message on disk.

    Apple stores messages under the account UUID / folder.mbox / batch / Data / .../Messages/<id>.emlx
    Strategy: look for files whose basename starts with the Mail message's remote id.
    """
    if not remote_id:
        return None
    # Pull out the numeric prefix of the remote id if present
    stem = remote_id.split(":")[-1][:40]
    inbox_dir = MAIL_ROOT / EXCHANGE_ACCOUNT_UUID / "Inbox.mbox"
    if not inbox_dir.exists():
        return None
    for match in inbox_dir.rglob("*.emlx"):
        if match.stem.startswith(stem) or match.stem == str(message_rowid):
            return match
    return None


def _parse_emlx(path: Path) -> dict[str, Any]:
    """Parse Apple's .emlx format: <bytelen>\n<rfc822 message>\n<plist trailer>."""
    raw = path.read_bytes()
    first_newline = raw.index(b"\n")
    length = int(raw[:first_newline])
    body_bytes = raw[first_newline + 1 : first_newline + 1 + length]
    msg = email.message_from_bytes(body_bytes, policy=email.policy.default)
    text = ""
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            if ctype == "text/plain":
                text = part.get_content()
                break
        if not text:
            for part in msg.walk():
                if part.get_content_type() == "text/html":
                    html = part.get_content()
                    text = re.sub(r"<[^>]+>", "", html)
                    text = re.sub(r"\s+\n", "\n", text)
                    break
    else:
        text = msg.get_content()
    return {
        "from": msg.get("From", ""),
        "to": msg.get("To", ""),
        "cc": msg.get("Cc", ""),
        "subject": msg.get("Subject", ""),
        "date": msg.get("Date", ""),
        "body": text.strip(),
    }


@mcp.tool()
def exchange_list_folders() -> list[dict]:
    """List Exchange (GMU) mail folders with unread/total counts."""
    with _connect() as conn:
        rows = conn.execute(
            f"SELECT ROWID, url, total_count, unread_count "
            f"FROM mailboxes WHERE url LIKE 'ews://{EXCHANGE_ACCOUNT_UUID}/%'"
        ).fetchall()
        return [
            {
                "id": r["ROWID"],
                "name": urllib.parse.unquote(r["url"].split("/", 3)[-1]),
                "total": r["total_count"],
                "unread": r["unread_count"],
            }
            for r in rows
        ]


@mcp.tool()
def exchange_search(
    query: str = "",
    since_hours: int = 24,
    folder: str = "Inbox",
    max_results: int = 50,
    unread_only: bool = False,
) -> list[dict]:
    """Search GMU Exchange mail locally (Apple Mail cache).

    query: case-insensitive substring to match in subject OR sender (leave blank for all).
    since_hours: only messages from the last N hours.
    folder: folder name (default Inbox). Use exchange_list_folders() to see options.
    max_results: cap (default 50).
    unread_only: if true, only unread messages.
    """
    with _connect() as conn:
        mbox_id = _mailbox_id(conn, folder)
        if mbox_id is None:
            return []
        cutoff = int((datetime.now(tz=timezone.utc) - timedelta(hours=since_hours)).timestamp())
        sql = """
            SELECT m.ROWID as id, m.date_sent, m.read, m.flagged, m.remote_id,
                   s.subject as subject, a.address as from_addr, a.comment as from_name
            FROM messages m
            LEFT JOIN subjects s ON s.ROWID = m.subject
            LEFT JOIN addresses a ON a.ROWID = m.sender
            WHERE m.mailbox = ?
              AND m.date_sent >= ?
        """
        params: list[Any] = [mbox_id, cutoff]
        if unread_only:
            sql += " AND m.read = 0"
        if query:
            sql += " AND (s.subject LIKE ? OR a.address LIKE ? OR a.comment LIKE ?)"
            like = f"%{query}%"
            params += [like, like, like]
        sql += " ORDER BY m.date_sent DESC LIMIT ?"
        params.append(min(max_results, 200))
        rows = conn.execute(sql, params).fetchall()
        return [
            {
                "id": r["id"],
                "date": _fmt_date(r["date_sent"]),
                "read": bool(r["read"]),
                "flagged": bool(r["flagged"]),
                "from": r["from_name"] or r["from_addr"] or "",
                "from_email": r["from_addr"] or "",
                "subject": r["subject"] or "",
                "remote_id": r["remote_id"] or "",
            }
            for r in rows
        ]


@mcp.tool()
def exchange_read(message_id: int) -> dict:
    """Read full body of a GMU Exchange message by its Envelope Index ROWID."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT remote_id FROM messages WHERE ROWID = ?", (message_id,)
        ).fetchone()
        if not row:
            return {"error": f"message {message_id} not found"}
        path = _find_emlx(message_id, row["remote_id"])
        if not path:
            return {"error": "emlx file not cached locally", "remote_id": row["remote_id"]}
        return _parse_emlx(path)


if __name__ == "__main__":
    mcp.run()
