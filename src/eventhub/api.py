"""FastAPI application factory."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

from . import accounts, routes_auth, routes_events, routes_users
from .config import AppConfig
from .db import init_pool
from .security import PasswordPolicyError

_STATIC_ERRORS: dict[type[Exception], tuple[int, str]] = {
    accounts.DuplicateUserError: (409, "Username already exists"),
    accounts.UserNotFoundError: (404, "User not found"),
    accounts.LastAdminError: (409, "At least one active administrator is required"),
}


def _static_handler(
    status_code: int, message: str
) -> Callable[[Request, Exception], Awaitable[JSONResponse]]:
    async def handler(_: Request, __: Exception) -> JSONResponse:
        return JSONResponse({"detail": message}, status_code=status_code)

    return handler


async def _validation_message_handler(_: Request, exc: Exception) -> JSONResponse:
    # These exceptions carry messages written by this application, never user input or SQL.
    return JSONResponse({"detail": str(exc)}, status_code=422)


def create_app(config: AppConfig | None = None) -> FastAPI:
    config = config or AppConfig.from_env()

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        init_pool(config.db)
        yield

    docs = config.enable_docs
    app = FastAPI(
        title="EventHub",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs" if docs else None,
        redoc_url=None,
        openapi_url="/openapi.json" if docs else None,
    )
    app.state.config = config

    @app.middleware("http")
    async def security_headers(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    for exc_type, (code, message) in _STATIC_ERRORS.items():
        app.add_exception_handler(exc_type, _static_handler(code, message))
    app.add_exception_handler(PasswordPolicyError, _validation_message_handler)
    app.add_exception_handler(accounts.InvalidUsernameError, _validation_message_handler)

    @app.get("/health", tags=["ops"])
    def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(routes_auth.router)
    app.include_router(routes_users.router)
    app.include_router(routes_events.router)
    return app
