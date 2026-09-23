"""One-time Google OAuth authorization: `python -m utils.setup_oauth`."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from config import get_settings
from utils.oauth import run_oauth_flow


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
    settings = get_settings()
    credentials_path = Path(settings.GOOGLE_CREDENTIALS_PATH)
    if not credentials_path.is_file():
        print(
            f"Missing {credentials_path}. In Google Cloud Console, create an OAuth "
            "Desktop client, enable Gmail API and Calendar API, then download the "
            "JSON file as credentials.json in this folder."
        )
        sys.exit(1)

    run_oauth_flow(settings)
    print(f"Authorization complete. Token saved to {settings.GOOGLE_TOKEN_PATH}.")


if __name__ == "__main__":
    main()
