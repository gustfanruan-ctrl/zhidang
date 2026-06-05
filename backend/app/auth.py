from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .config import settings

security = HTTPBearer(auto_error=False)


def create_jwt(payload: dict[str, Any]) -> str:
    body = {**payload, "exp": datetime.now(timezone.utc) + timedelta(hours=settings.jwt_exp_hours)}
    return jwt.encode(body, settings.jwt_secret, algorithm="HS256")


def decode_jwt(token: str) -> dict[str, Any]:
    return jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])


def get_current_user(credentials: HTTPAuthorizationCredentials | None = Depends(security)) -> dict[str, Any]:
    if not credentials:
        raise HTTPException(status_code=401, detail="未登录")
    try:
        return decode_jwt(credentials.credentials)
    except Exception as exc:
        raise HTTPException(status_code=401, detail="登录已失效") from exc


def get_current_user_for_sse(request: Request) -> dict[str, Any]:
    """Auth helper for SSE endpoints.

    Browser EventSource cannot set custom headers, so the token is passed via
    `?token=` query string. Falls back to `Authorization: Bearer` header for
    non-browser clients (curl, tests).
    """
    token = request.query_params.get("token")
    if not token:
        header = request.headers.get("authorization") or request.headers.get("Authorization")
        if header and header.lower().startswith("bearer "):
            token = header.split(" ", 1)[1].strip()
    if not token:
        raise HTTPException(status_code=401, detail="未登录")
    try:
        return decode_jwt(token)
    except Exception as exc:
        raise HTTPException(status_code=401, detail="登录已失效") from exc


def require_superadmin(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    if user.get("source") != "superadmin":
        raise HTTPException(status_code=403, detail="权限不足")
    return user


def require_user(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    if user.get("source") != "user":
        raise HTTPException(status_code=403, detail="权限不足")
    return user


def require_any_auth(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    if user.get("source") not in {"superadmin", "user", "sso"}:
        raise HTTPException(status_code=403, detail="权限不足")
    return user
