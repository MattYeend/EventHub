"""Request and response models for authentication and user administration."""

from __future__ import annotations

from typing import Self

from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator

from .accounts import Role


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LoginRequest(_Strict):
    username: str = Field(min_length=1, max_length=64)
    password: SecretStr = Field(min_length=1, max_length=128)


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"  # noqa: S105  (a label, not a credential)
    expires_in: int
    must_change_password: bool


class ChangePasswordRequest(_Strict):
    current_password: SecretStr = Field(min_length=1, max_length=128)
    new_password: SecretStr = Field(min_length=1, max_length=128)


class UserCreate(_Strict):
    username: str = Field(min_length=3, max_length=64)
    password: SecretStr = Field(min_length=1, max_length=128)
    role: Role


class UserUpdate(_Strict):
    role: Role | None = None
    is_active: bool | None = None

    @model_validator(mode="after")
    def _at_least_one_field(self) -> Self:
        if self.role is None and self.is_active is None:
            raise ValueError("Provide role, is_active or both")
        return self


class PasswordReset(_Strict):
    new_password: SecretStr = Field(min_length=1, max_length=128)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    role: Role
    is_active: bool
    must_change_password: bool
