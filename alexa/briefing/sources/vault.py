"""
Vault snapshot source.

GitHub Actions runners cannot see Derek's Obsidian vault — it lives on his Mac.
To keep the briefing vault-aware without exfiltrating anything public, we use a
**private gist** as a one-way bridge:

1. A local Mac task (`vault-snapshot.sh`) runs nightly and PATCHes a private
   gist with a JSON blob containing:
      {
        "updated": "2026-04-15T23:05:00Z",
        "priorities": [ "Tesla auto repair business -- launching late May", ... ],
        "deadlines": [ {"what": "HIST-378 exhibit", "date": "2026-04-28"}, ... ],
        "people_notes": [ {"who": "Jillian", "latest": "visiting this weekend"}, ... ]
      }
2. This module reads that gist in the cloud runner and hands the contents to
   deadlines.py and the voice layer.

The cloud runner never sees raw vault text, only the pre-digested snapshot.

Env vars:
    VAULT_SNAPSHOT_GIST_ID    — id of the private gist
    GIST_TOKEN                — GitHub PAT with `gist` scope (read is enough)
"""

from __future__ import annotations

import json
import os
from typing import Any

import requests


_API_BASE = "https://api.github.com"


def _snapshot() -> dict:
    gist_id = os.environ.get("VAULT_SNAPSHOT_GIST_ID")
    token = os.environ.get("GIST_TOKEN")
    if not (gist_id and token):
        return {}

    try:
        resp = requests.get(
            f"{_API_BASE}/gists/{gist_id}",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=15,
        )
        if resp.status_code != 200:
            return {}
        files = resp.json().get("files", {})
        # We expect a single JSON file named `vault-snapshot.json`.
        for meta in files.values():
            content = meta.get("content", "")
            if not content:
                continue
            try:
                return json.loads(content)
            except Exception:
                continue
    except Exception:
        return {}
    return {}


def fetch_vault() -> dict[str, Any]:
    """
    Return:
        {
          "priorities": ["...", "...", ...],    # strings, already Sheldon-voiced
          "deadlines": [{"what": "...", "date": "YYYY-MM-DD"}, ...],
          "updated": iso8601 string or None,
          "error": None or str,
        }
    """
    snap = _snapshot()
    if not snap:
        return {
            "priorities": [],
            "deadlines": [],
            "updated": None,
            "error": "vault snapshot unavailable (env or gist missing)",
        }

    return {
        "priorities": snap.get("priorities", [])[:5],
        "deadlines": snap.get("deadlines", []),
        "updated": snap.get("updated"),
        "error": None,
    }
