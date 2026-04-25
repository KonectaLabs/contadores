"""Primitive auth endpoints for cookie-based session login."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from backend.auth import SESSION_COOKIE_NAME, auth_manager

auth_router = APIRouter(prefix="/api/auth", tags=["auth"])


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
async def login(payload: LoginRequest, response: Response) -> AuthStatusResponse:
    """Authenticate one configured account and issue a session cookie."""
    if not auth_manager.enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Auth is disabled (AUTH_DISABLE=true).",
        )
    normalized_user = auth_manager.authenticate(payload.user, payload.password)
    if not normalized_user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid user or password.",
        )

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
