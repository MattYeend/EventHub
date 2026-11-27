"""Authentication endpoints."""

from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, HTTPException, Request, Response, status

from . import accounts, audit
from .deps import (
    BearerDep,
    ConfigDep,
    ConnDep,
    CurrentUser,
    client_ip,
    unauthorised,
)
from .schemas import ChangePasswordRequest, LoginRequest, TokenOut, UserOut
from .security import utcnow

router = APIRouter(tags=["auth"])


@router.post("/auth/login", response_model=TokenOut)
def login(body: LoginRequest, request: Request, conn: ConnDep, config: ConfigDep) -> TokenOut:
    now = utcnow()
    try:
        user = accounts.authenticate(
            conn,
            body.username,
            body.password.get_secret_value(),
            now=now,
            client_ip=client_ip(request),
        )
    except accounts.AuthenticationError:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Invalid credentials",
            headers={"WWW-Authenticate": "Bearer"},
        ) from None
    ttl = timedelta(minutes=config.session_ttl_minutes)
    token, _ = accounts.create_session(conn, user.id, ttl, now)
    return TokenOut(
        access_token=token,
        expires_in=int(ttl.total_seconds()),
        must_change_password=user.must_change_password,
    )


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(user: CurrentUser, credentials: BearerDep, conn: ConnDep) -> Response:
    if credentials is None:
        raise unauthorised()
    accounts.revoke_session(conn, credentials.credentials, utcnow())
    audit.record(conn, "auth.logout", actor_id=user.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/auth/change-password", status_code=status.HTTP_204_NO_CONTENT)
def change_password(
    body: ChangePasswordRequest, request: Request, user: CurrentUser, conn: ConnDep
) -> Response:
    try:
        accounts.change_own_password(
            conn,
            user,
            body.current_password.get_secret_value(),
            body.new_password.get_secret_value(),
            client_ip=client_ip(request),
        )
    except accounts.AuthenticationError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Current password is incorrect") from None
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/me", response_model=UserOut)
def me(user: CurrentUser) -> UserOut:
    return UserOut.model_validate(user)
