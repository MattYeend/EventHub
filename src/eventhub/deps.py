"""Shared FastAPI dependencies: database access, authentication and roles."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from . import accounts
from .accounts import Role, User
from .config import AppConfig
from .db import Connection, get_connection
from .security import utcnow

bearer_scheme = HTTPBearer(auto_error=False)


def get_conn() -> Iterator[Connection]:
    with get_connection() as conn:
        yield conn


def get_config(request: Request) -> AppConfig:
    config: AppConfig = request.app.state.config
    return config


def client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


ConnDep = Annotated[Connection, Depends(get_conn, scope="function")]
ConfigDep = Annotated[AppConfig, Depends(get_config)]
BearerDep = Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)]


def unauthorised() -> HTTPException:
    return HTTPException(
        status.HTTP_401_UNAUTHORIZED,
        "Invalid or expired credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )


def current_user(credentials: BearerDep, conn: ConnDep) -> User:
    """Resolve the bearer token to an active user. Allowed even if a password change is due."""
    if credentials is None:
        raise unauthorised()
    user = accounts.resolve_session(conn, credentials.credentials, utcnow())
    if user is None:
        raise unauthorised()
    return user


CurrentUser = Annotated[User, Depends(current_user)]


def active_user(user: CurrentUser) -> User:
    """Block everything except password change and logout until the password is replaced."""
    if user.must_change_password:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Password change required")
    return user


def require_roles(*roles: Role) -> Callable[[User], User]:
    allowed = frozenset(roles)

    def checker(user: Annotated[User, Depends(active_user)]) -> User:
        if user.role not in allowed:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient permissions")
        return user

    return checker
