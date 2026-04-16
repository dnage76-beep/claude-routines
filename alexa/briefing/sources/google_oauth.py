"""
Shared Google OAuth helper. Uses a single refresh token plus client_id and
client_secret passed as env vars (GitHub Secrets) to mint access tokens on
demand. No client libraries required — one POST to the token endpoint.

Env vars expected:
    GOOGLE_CLIENT_ID
    GOOGLE_CLIENT_SECRET
    GOOGLE_REFRESH_TOKEN

Derek generates the refresh token once locally (see README.md "Bootstrapping
OAuth") and uploads it to GitHub with `gh secret set`.
"""

from __future__ import annotations

import os
import time

import requests

_TOKEN_URL = "https://oauth2.googleapis.com/token"

_cache: dict = {"access_token": None, "expires_at": 0.0}


def get_access_token() -> str:
    """Return a valid bearer token. Refreshes lazily, caches in memory."""
    now = time.time()
    if _cache["access_token"] and _cache["expires_at"] > now + 30:
        return _cache["access_token"]

    client_id = os.environ.get("GOOGLE_CLIENT_ID")
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET")
    refresh_token = os.environ.get("GOOGLE_REFRESH_TOKEN")
    if not (client_id and client_secret and refresh_token):
        raise RuntimeError(
            "Google OAuth env vars missing. Set GOOGLE_CLIENT_ID, "
            "GOOGLE_CLIENT_SECRET, GOOGLE_REFRESH_TOKEN."
        )

    resp = requests.post(
        _TOKEN_URL,
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        },
        timeout=15,
    )
    resp.raise_for_status()
    payload = resp.json()
    _cache["access_token"] = payload["access_token"]
    _cache["expires_at"] = now + payload.get("expires_in", 3500)
    return _cache["access_token"]


def auth_headers() -> dict:
    return {"Authorization": f"Bearer {get_access_token()}"}
