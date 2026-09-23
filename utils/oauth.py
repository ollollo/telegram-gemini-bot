"""Google OAuth2 helpers for personal Gmail and Calendar access."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

if TYPE_CHECKING:
    from config import Settings

logger = logging.getLogger(__name__)

GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/calendar",
]


def run_oauth_flow(settings: Settings) -> Credentials:
    """Open a local browser flow and persist `token.json`."""

    credentials_path = Path(settings.GOOGLE_CREDENTIALS_PATH)
    token_path = Path(settings.GOOGLE_TOKEN_PATH)
    if not credentials_path.is_file():
        raise FileNotFoundError(
            f"OAuth client file not found: {credentials_path}. "
            "Download credentials.json from Google Cloud Console."
        )

    flow = InstalledAppFlow.from_client_secrets_file(str(credentials_path), GOOGLE_SCOPES)
    creds = flow.run_local_server(port=0)
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(creds.to_json(), encoding="utf-8")
    logger.info("Saved Google OAuth token to %s", token_path)
    return creds


def load_google_credentials(settings: Settings) -> Credentials | None:
    """Load and refresh stored OAuth credentials, or return None if missing."""

    token_path = Path(settings.GOOGLE_TOKEN_PATH)
    credentials_path = Path(settings.GOOGLE_CREDENTIALS_PATH)
    creds: Credentials | None = None

    if token_path.is_file():
        creds = Credentials.from_authorized_user_file(str(token_path), GOOGLE_SCOPES)

    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            token_path.write_text(creds.to_json(), encoding="utf-8")
            return creds
        except Exception:
            logger.exception("Failed to refresh Google OAuth token")
            return None

    if not credentials_path.is_file():
        logger.warning("Google credentials file missing at %s", credentials_path)
    else:
        logger.warning(
            "Google token missing at %s. Run: python -m utils.setup_oauth",
            token_path,
        )
    return None
