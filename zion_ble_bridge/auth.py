"""Authentication helpers for the BLE bridge API."""

from __future__ import annotations

import secrets

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .config import Settings

_bearer = HTTPBearer(auto_error=False)


def require_request_auth(settings: Settings):
    """Create a FastAPI dependency that enforces the configured bearer token."""

    async def _require_request_auth(
        credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    ) -> None:
        if settings.auth_token is None:
            return

        token = credentials.credentials if credentials else None
        if token is None or not secrets.compare_digest(token, settings.auth_token):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid bridge token",
            )

    return _require_request_auth
