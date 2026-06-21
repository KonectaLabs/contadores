"""Primitive auth endpoints for cookie-based session login."""

from __future__ import annotations

import os
import time
from threading import Lock

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from backend.auth import SESSION_COOKIE_NAME, auth_manager

auth_router = APIRouter(prefix="/api/auth", tags=["auth"])
INVALID_LOGIN_DETAIL = "Invalid user or password."


def _parse_int_env(name: str, default: int, *, minimum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        return default
    return max(minimum, value)


def _normalized_login_key(value: str) -> str:
    return value.strip().lower() or "unknown"


def _client_ip(request: Request) -> str:
    forwarded_for = request.headers.get("x-forwarded-for", "")
    first_forwarded = forwarded_for.split(",", 1)[0].strip()
    if first_forwarded:
        return first_forwarded
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


class LoginThrottle:
    """Small in-memory failed-login throttle."""

    def __init__(self) -> None:
        self._attempts: dict[str, list[float]] = {}
        self._lock = Lock()
        self._now = time.monotonic

    def reset(self, *, now=None) -> None:
        with self._lock:
            self._attempts = {}
            self._now = now or time.monotonic

    def retry_after(self, *, user: str, client_ip: str) -> int:
        with self._lock:
            return self._retry_after_locked(user=user, client_ip=client_ip)

    def record_failure(self, *, user: str, client_ip: str) -> int:
        with self._lock:
            now = self._now()
            window_seconds = self._window_seconds
            cutoff = now - window_seconds
            for key in self._keys(user=user, client_ip=client_ip):
                attempts = [attempt for attempt in self._attempts.get(key, []) if attempt > cutoff]
                attempts.append(now)
                self._attempts[key] = attempts
            return self._retry_after_locked(user=user, client_ip=client_ip)

    def record_success(self, *, user: str, client_ip: str) -> None:
        with self._lock:
            for key in self._keys(user=user, client_ip=client_ip):
                self._attempts.pop(key, None)

    def _retry_after_locked(self, *, user: str, client_ip: str) -> int:
        now = self._now()
        window_seconds = self._window_seconds
        cutoff = now - window_seconds
        retry_after = 0
        for key in self._keys(user=user, client_ip=client_ip):
            attempts = [attempt for attempt in self._attempts.get(key, []) if attempt > cutoff]
            self._attempts[key] = attempts
            if len(attempts) >= self._failure_limit:
                retry_after = max(retry_after, int(window_seconds - (now - attempts[0])))
        return max(0, retry_after)

    @property
    def _failure_limit(self) -> int:
        return _parse_int_env("AUTH_LOGIN_FAILURE_LIMIT", 5, minimum=1)

    @property
    def _window_seconds(self) -> int:
        return _parse_int_env("AUTH_LOGIN_WINDOW_SECONDS", 300, minimum=1)

    @staticmethod
    def _keys(*, user: str, client_ip: str) -> tuple[str, str]:
        return (
            f"user:{_normalized_login_key(user)}",
            f"ip:{client_ip.strip() or 'unknown'}",
        )


login_throttle = LoginThrottle()


class LoginRequest(BaseModel):
    """Credentials payload for primitive auth."""

    user: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=2048)


class AuthStatusResponse(BaseModel):
    """Current auth state for frontend checks."""

    authenticated: bool
    user: str | None = None


def apply_session_cookie(response: Response, token: str) -> None:
    """Write the HttpOnly auth cookie."""
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        max_age=auth_manager.session_max_age_seconds,
        httponly=True,
        samesite="strict",
        secure=auth_manager.cookie_secure,
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    """Clear the auth cookie from browser state."""
    response.delete_cookie(
        key=SESSION_COOKIE_NAME,
        path="/",
        httponly=True,
        samesite="strict",
        secure=auth_manager.cookie_secure,
    )


@auth_router.post("/login", response_model=AuthStatusResponse)
async def login(payload: LoginRequest, request: Request, response: Response) -> AuthStatusResponse:
    """Authenticate one configured account and issue a session cookie."""
    if not auth_manager.enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Auth is disabled (AUTH_DISABLE=true).",
        )
    client_ip = _client_ip(request)
    retry_after = login_throttle.retry_after(user=payload.user, client_ip=client_ip)
    if retry_after:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many login attempts. Try again later.",
            headers={"Retry-After": str(retry_after)},
        )

    normalized_user = auth_manager.authenticate(payload.user, payload.password)
    if not normalized_user:
        retry_after = login_throttle.record_failure(user=payload.user, client_ip=client_ip)
        if retry_after:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many login attempts. Try again later.",
                headers={"Retry-After": str(retry_after)},
            )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=INVALID_LOGIN_DETAIL,
        )

    login_throttle.record_success(user=payload.user, client_ip=client_ip)
    session_token = auth_manager.create_session(normalized_user)
    apply_session_cookie(response, session_token)
    return AuthStatusResponse(authenticated=True, user=normalized_user)


@auth_router.post("/logout", response_model=AuthStatusResponse)
async def logout(request: Request, response: Response) -> AuthStatusResponse:
    """Invalidate current session cookie if present."""
    session_token = request.cookies.get(SESSION_COOKIE_NAME)
    auth_manager.revoke_session(session_token)
    clear_session_cookie(response)
    return AuthStatusResponse(authenticated=False)


@auth_router.get("/me", response_model=AuthStatusResponse)
async def get_current_auth(request: Request) -> AuthStatusResponse:
    """Resolve current cookie session."""
    session_token = request.cookies.get(SESSION_COOKIE_NAME)
    current_user = auth_manager.resolve_session(session_token)
    if not current_user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required.",
        )
    return AuthStatusResponse(authenticated=True, user=current_user)
