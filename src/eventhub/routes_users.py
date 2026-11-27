"""User administration endpoints (administrators only)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Response, status

from . import accounts
from .accounts import Role, User, UserNotFoundError
from .deps import ConnDep, require_roles
from .schemas import PasswordReset, UserCreate, UserOut, UserUpdate

router = APIRouter(prefix="/users", tags=["users"])

AdminUser = Annotated[User, Depends(require_roles(Role.ADMIN))]
UserId = Annotated[int, Path(ge=1)]


@router.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def create_user(body: UserCreate, conn: ConnDep, admin: AdminUser) -> UserOut:
    user = accounts.create_user(
        conn,
        body.username,
        body.password.get_secret_value(),
        body.role,
        actor_id=admin.id,
    )
    return UserOut.model_validate(user)


@router.get("", response_model=list[UserOut])
def list_users(
    conn: ConnDep,
    admin: AdminUser,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
) -> list[UserOut]:
    return [UserOut.model_validate(u) for u in accounts.list_users(conn, limit, offset)]


@router.get("/{user_id}", response_model=UserOut)
def get_user(user_id: UserId, conn: ConnDep, admin: AdminUser) -> UserOut:
    user = accounts.get_user(conn, user_id)
    if user is None:
        raise UserNotFoundError(user_id)
    return UserOut.model_validate(user)


@router.patch("/{user_id}", response_model=UserOut)
def update_user(user_id: UserId, body: UserUpdate, conn: ConnDep, admin: AdminUser) -> UserOut:
    user = accounts.update_user(
        conn, user_id, role=body.role, is_active=body.is_active, actor_id=admin.id
    )
    return UserOut.model_validate(user)


@router.post("/{user_id}/reset-password", status_code=status.HTTP_204_NO_CONTENT)
def reset_password(
    user_id: UserId, body: PasswordReset, conn: ConnDep, admin: AdminUser
) -> Response:
    accounts.set_password(
        conn,
        user_id,
        body.new_password.get_secret_value(),
        must_change=True,
        actor_id=admin.id,
        action="user.password_reset",
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
