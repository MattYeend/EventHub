"""Configuration loaded from environment variables only."""
 
from __future__ import annotations
 
import os
from dataclasses import dataclass, field
 
ENVIRONMENTS = frozenset({"development", "production"})
 
 
class ConfigError(RuntimeError):
    """Raised when required configuration is missing or invalid."""
 
 
def _require(key: str) -> str:
    value = os.environ.get(key, "").strip()
    if not value:
        raise ConfigError(f"Missing required environment variable: {key}")
    return value
 
 
def _int(key: str, default: int, minimum: int, maximum: int) -> int:
    raw = os.environ.get(key, "").strip() or str(default)
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigError(f"{key} must be an integer") from exc
    if not minimum <= value <= maximum:
        raise ConfigError(f"{key} must be between {minimum} and {maximum}")
    return value
 
 
def _flag(key: str) -> bool:
    return os.environ.get(key, "").strip().lower() in {"1", "true", "yes"}
 
 
@dataclass(frozen=True, slots=True)
class DbConfig:
    host: str
    port: int
    user: str
    database: str
    ssl_ca: str | None
    ssl_verify: bool
    pool_size: int
    password: str = field(repr=False)  # never printed in repr, logs or tracebacks
 
    @classmethod
    def from_env(cls, environment: str) -> DbConfig:
        # TLS is always used. Certificate verification may only be relaxed in development,
        # where the local database presents a self-signed certificate.
        ssl_verify = os.environ.get("DB_SSL_VERIFY", "true").strip().lower() not in {
            "0",
            "false",
            "no",
        }
        if not ssl_verify and environment != "development":
            raise ConfigError("DB_SSL_VERIFY=false is only permitted when APP_ENV=development")
        return cls(
            host=_require("DB_HOST"),
            port=_int("DB_PORT", 3306, 1, 65535),
            user=_require("DB_USER"),
            password=_require("DB_PASSWORD"),
            database=_require("DB_NAME"),
            ssl_ca=_require("DB_SSL_CA") if ssl_verify else None,
            ssl_verify=ssl_verify,
            pool_size=_int("DB_POOL_SIZE", 10, 1, 32),
        )
 
 
@dataclass(frozen=True, slots=True)
class AppConfig:
    environment: str
    session_ttl_minutes: int
    enable_docs: bool
    db: DbConfig
 
    @classmethod
    def from_env(cls) -> AppConfig:
        # Secure by default: anything unset is treated as production.
        environment = os.environ.get("APP_ENV", "production").strip().lower()
        if environment not in ENVIRONMENTS:
            raise ConfigError("APP_ENV must be 'development' or 'production'")
        enable_docs = _flag("ENABLE_DOCS")
        if enable_docs and environment != "development":
            raise ConfigError("ENABLE_DOCS is only permitted when APP_ENV=development")
        return cls(
            environment=environment,
            session_ttl_minutes=_int("SESSION_TTL_MINUTES", 60, 5, 480),
            enable_docs=enable_docs,
            db=DbConfig.from_env(environment),
        )