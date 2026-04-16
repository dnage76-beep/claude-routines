"""One-time OAuth for a Gmail account.

Usage: python auth.py <account_nickname>

Reads config.json, opens browser, stores token at tokens/<nickname>.json.
"""
import json
import sys
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
ROOT = Path(__file__).parent
CREDENTIALS = ROOT / "credentials.json"
CONFIG = ROOT / "config.json"
TOKENS_DIR = ROOT / "tokens"


def main() -> None:
    if len(sys.argv) != 2:
        print("Usage: python auth.py <account_nickname>")
        sys.exit(1)

    nickname = sys.argv[1]
    config = json.loads(CONFIG.read_text())
    if nickname not in config["accounts"]:
        print(f"Unknown account '{nickname}'. Configured: {list(config['accounts'])}")
        sys.exit(1)

    expected_email = config["accounts"][nickname]["email"]
    print(f"Authorizing '{nickname}' — sign in as {expected_email}.")

    flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS), SCOPES)
    creds = flow.run_local_server(port=0)

    TOKENS_DIR.mkdir(exist_ok=True)
    token_path = TOKENS_DIR / f"{nickname}.json"
    token_path.write_text(creds.to_json())
    print(f"Saved token to {token_path}")


if __name__ == "__main__":
    main()
