"""Token handling for the web API."""

import os
import secrets
from pathlib import Path
from typing import Optional

from fastapi import Header, HTTPException, Query, status


DEFAULT_TOKEN_FILE = Path.home() / ".disk-space-manager-web-token"


def get_or_create_token(
    configured_token: Optional[str] = None,
    token_file: Path = DEFAULT_TOKEN_FILE,
) -> str:
    """Return a configured token or create a local token file."""
    if configured_token:
        return configured_token

    env_token = os.environ.get("DISK_SPACE_MANAGER_WEB_TOKEN")
    if env_token:
        return env_token

    try:
        if token_file.exists():
            token = token_file.read_text(encoding="utf-8").strip()
            if token:
                return token
    except OSError:
        pass

    token = secrets.token_urlsafe(32)
    try:
        token_file.write_text(token + "\n", encoding="utf-8")
        token_file.chmod(0o600)
    except OSError:
        # The server can still run with an in-memory token printed at startup.
        pass
    return token


def make_token_dependency(expected_token: str):
    """Create a FastAPI dependency that checks bearer/header/query tokens."""

    def verify_token(
        authorization: Optional[str] = Header(default=None),
        x_api_token: Optional[str] = Header(default=None),
        token: Optional[str] = Query(default=None),
    ) -> None:
        supplied = token or x_api_token
        if not supplied and authorization:
            prefix = "Bearer "
            if authorization.startswith(prefix):
                supplied = authorization[len(prefix):]

        if not supplied or not secrets.compare_digest(supplied, expected_token):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Valid API token required",
            )

    return verify_token
