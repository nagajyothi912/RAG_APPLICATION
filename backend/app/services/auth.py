"""
Role-based login: a `chatbot` role and an `admin` role.

Tokens are `<base64url payload>.<base64url HMAC-SHA256>` signed with
AUTH_SECRET - stdlib only, no JWT dependency. The payload carries the username,
role and expiry, so verifying a request needs no session store.

Route protection lives in two FastAPI dependencies:
  current_user  - any signed-in role (chat, the document list, golden questions)
  require_admin - admin only (upload/delete, every week's evaluation routes)

With AUTH_ENABLED=false both dependencies return a synthetic admin, which is
how the test suite exercises the routes without logging in.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import secrets
import time
from dataclasses import dataclass
from typing import Literal, Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import settings

logger = logging.getLogger(__name__)

Role = Literal["chatbot", "admin"]
ROLES: tuple[Role, ...] = ("chatbot", "admin")

_bearer = HTTPBearer(auto_error=False)
_process_secret = secrets.token_urlsafe(32)


@dataclass(frozen=True)
class AuthUser:
    username: str
    role: Role

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


def _secret() -> bytes:
    return (settings.auth_secret.strip() or _process_secret).encode("utf-8")


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _sign(payload: str) -> str:
    return _b64(hmac.new(_secret(), payload.encode("ascii"), hashlib.sha256).digest())


def _accounts() -> dict[str, tuple[str, Role]]:
    return {
        settings.admin_username: (settings.admin_password, "admin"),
        settings.chatbot_username: (settings.chatbot_password, "chatbot"),
    }


def authenticate(username: str, password: str) -> Optional[AuthUser]:
    """The account for these credentials, or None. Constant-time on the password."""
    account = _accounts().get(username.strip())
    # An unknown username still runs a comparison, so it costs the same as a wrong password.
    expected, role = account if account else (secrets.token_urlsafe(16), "chatbot")
    if not hmac.compare_digest(password.encode("utf-8"), expected.encode("utf-8")) or account is None:
        return None
    return AuthUser(username=username.strip(), role=role)


def issue_token(user: AuthUser) -> tuple[str, int]:
    """A signed token for `user`, and its expiry as a unix timestamp."""
    expires_at = int(time.time()) + settings.auth_token_ttl_minutes * 60
    body = json.dumps(
        {"sub": user.username, "role": user.role, "exp": expires_at},
        separators=(",", ":"),
    )
    payload = _b64(body.encode("utf-8"))
    return f"{payload}.{_sign(payload)}", expires_at


def verify_token(token: str) -> Optional[AuthUser]:
    """The user a token was issued to, or None if it is forged, malformed or expired."""
    try:
        payload, signature = token.split(".", 1)
    except ValueError:
        return None
    if not hmac.compare_digest(signature, _sign(payload)):
        return None
    try:
        data = json.loads(_unb64(payload))
    except (ValueError, json.JSONDecodeError):
        return None
    if data.get("role") not in ROLES or int(data.get("exp", 0)) < time.time():
        return None
    return AuthUser(username=str(data.get("sub", "")), role=data["role"])


def current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> AuthUser:
    if not settings.auth_enabled:
        return AuthUser(username="auth-disabled", role="admin")
    user = verify_token(credentials.credentials) if credentials else None
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Sign in to continue.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


def require_admin(user: AuthUser = Depends(current_user)) -> AuthUser:
    if not user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This action needs the admin role.",
        )
    return user


def warn_on_default_credentials() -> None:
    if not settings.auth_enabled:
        logger.warning("AUTH_ENABLED=false: every request is treated as admin.")
        return
    if settings.admin_password == "admin123" or settings.chatbot_password == "user123":
        logger.warning(
            "Using the default demo passwords. Set ADMIN_PASSWORD and CHATBOT_PASSWORD in backend/.env."
        )
    if not settings.auth_secret.strip():
        logger.info("AUTH_SECRET is not set; sessions end when the server restarts.")
