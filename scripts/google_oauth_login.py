from __future__ import annotations

import argparse
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow


SCOPES = [
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/spreadsheets",
]


def main() -> None:
    parser = argparse.ArgumentParser(description="Create Google OAuth token for AIcallorder.")
    parser.add_argument("--client", required=True, help="Path to OAuth client JSON from Google Cloud Console.")
    parser.add_argument("--token", required=True, help="Output path for authorized user token JSON.")
    args = parser.parse_args()

    client_path = Path(args.client)
    token_path = Path(args.token)
    token_path.parent.mkdir(parents=True, exist_ok=True)

    flow = InstalledAppFlow.from_client_secrets_file(str(client_path), SCOPES)
    creds = flow.run_local_server(
        host="localhost",
        port=0,
        access_type="offline",
        prompt="consent",
    )
    token_path.write_text(creds.to_json(), encoding="utf-8")
    print(f"OAuth token saved to {token_path}")


if __name__ == "__main__":
    main()
