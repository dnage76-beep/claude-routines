"""Multi-account Gmail MCP server.

Exposes Gmail search/read across multiple authorized accounts. Each tool call
takes an `account` parameter matching a nickname in config.json.
"""
import base64
import json
from pathlib import Path
from typing import Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from mcp.server.fastmcp import FastMCP

ROOT = Path(__file__).parent
CONFIG = ROOT / "config.json"
TOKENS_DIR = ROOT / "tokens"
SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]

mcp = FastMCP("gmail-multi")


def _load_config() -> dict[str, Any]:
    return json.loads(CONFIG.read_text())


def _service(account: str):
    config = _load_config()
    if account not in config["accounts"]:
        raise ValueError(
            f"Unknown account '{account}'. Configured: {list(config['accounts'])}"
        )
    token_path = TOKENS_DIR / f"{account}.json"
    if not token_path.exists():
        raise RuntimeError(
            f"No token for '{account}'. Run: python auth.py {account}"
        )
    creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
    if not creds.valid and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        token_path.write_text(creds.to_json())
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def _header(headers: list[dict], name: str) -> str:
    for h in headers:
        if h["name"].lower() == name.lower():
            return h["value"]
    return ""


@mcp.tool()
def gmail_list_accounts() -> dict:
    """List configured Gmail account nicknames and their email addresses."""
    config = _load_config()
    return {
        nick: {
            "email": info["email"],
            "description": info.get("description", ""),
            "authorized": (TOKENS_DIR / f"{nick}.json").exists(),
        }
        for nick, info in config["accounts"].items()
    }


@mcp.tool()
def gmail_search(account: str, query: str, max_results: int = 20) -> list[dict]:
    """Search messages in the given account using Gmail query syntax.

    account: nickname from config (e.g. 'personal', 'secondary', 'gmu')
    query: Gmail search string, e.g. 'after:2026/04/15 -category:promotions'
    max_results: max messages to return (default 20, cap 100)
    """
    svc = _service(account)
    resp = (
        svc.users()
        .messages()
        .list(userId="me", q=query, maxResults=min(max_results, 100))
        .execute()
    )
    ids = [m["id"] for m in resp.get("messages", [])]
    results = []
    for mid in ids:
        msg = (
            svc.users()
            .messages()
            .get(userId="me", id=mid, format="metadata",
                 metadataHeaders=["From", "To", "Subject", "Date"])
            .execute()
        )
        headers = msg.get("payload", {}).get("headers", [])
        results.append({
            "id": mid,
            "threadId": msg.get("threadId"),
            "snippet": msg.get("snippet", ""),
            "labelIds": msg.get("labelIds", []),
            "from": _header(headers, "From"),
            "to": _header(headers, "To"),
            "subject": _header(headers, "Subject"),
            "date": _header(headers, "Date"),
        })
    return results


@mcp.tool()
def gmail_read(account: str, message_id: str) -> dict:
    """Read full content of a message (headers + decoded body)."""
    svc = _service(account)
    msg = (
        svc.users()
        .messages()
        .get(userId="me", id=message_id, format="full")
        .execute()
    )
    headers = msg.get("payload", {}).get("headers", [])

    def extract_body(part: dict) -> str:
        mime = part.get("mimeType", "")
        body = part.get("body", {})
        data = body.get("data")
        if data and mime == "text/plain":
            return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
        for sub in part.get("parts", []) or []:
            text = extract_body(sub)
            if text:
                return text
        if data and mime == "text/html":
            return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
        return ""

    return {
        "id": msg["id"],
        "threadId": msg.get("threadId"),
        "labelIds": msg.get("labelIds", []),
        "snippet": msg.get("snippet", ""),
        "from": _header(headers, "From"),
        "to": _header(headers, "To"),
        "cc": _header(headers, "Cc"),
        "subject": _header(headers, "Subject"),
        "date": _header(headers, "Date"),
        "body": extract_body(msg.get("payload", {})),
    }


if __name__ == "__main__":
    mcp.run()
