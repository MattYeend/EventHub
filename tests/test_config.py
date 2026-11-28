import pytest

from eventhub.config import AppConfig, ConfigError

ALL_KEYS = (
    "APP_ENV",
    "ENABLE_DOCS",
    "SESSION_TTL_MINUTES",
    "DB_HOST",
    "DB_PORT",
    "DB_USER",
    "DB_PASSWORD",
    "DB_NAME",
    "DB_POOL_SIZE",
    "DB_SSL_VERIFY",
    "DB_SSL_CA",
    "EVENT_RETENTION_MONTHS",
)
BASE = {
    "DB_HOST": "db.example.internal",
    "DB_USER": "app",
    "DB_PASSWORD": "s3cret-value",
    "DB_NAME": "eventhub",
    "DB_SSL_CA": "/etc/ssl/ca.pem",
}


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for key in ALL_KEYS:
        monkeypatch.delenv(key, raising=False)


def set_env(monkeypatch, **extra):
    for key, value in {**BASE, **extra}.items():
        monkeypatch.setenv(key, value)


def test_defaults_to_production_with_tls(monkeypatch):
    set_env(monkeypatch)
    config = AppConfig.from_env()
    assert config.environment == "production"
    assert config.db.ssl_verify is True
    assert config.enable_docs is False


def test_tls_ca_required_when_tls_enabled(monkeypatch):
    set_env(monkeypatch)
    monkeypatch.delenv("DB_SSL_CA")
    with pytest.raises(ConfigError):
        AppConfig.from_env()


def test_certificate_verification_can_only_be_relaxed_in_development(monkeypatch):
    set_env(monkeypatch, DB_SSL_VERIFY="false")
    with pytest.raises(ConfigError):
        AppConfig.from_env()
    set_env(monkeypatch, DB_SSL_VERIFY="false", APP_ENV="development")
    monkeypatch.delenv("DB_SSL_CA")
    config = AppConfig.from_env()
    assert config.db.ssl_verify is False
    assert config.db.ssl_ca is None


def test_docs_can_only_be_enabled_in_development(monkeypatch):
    set_env(monkeypatch, ENABLE_DOCS="true")
    with pytest.raises(ConfigError):
        AppConfig.from_env()


def test_unknown_environment_is_rejected(monkeypatch):
    set_env(monkeypatch, APP_ENV="staging")
    with pytest.raises(ConfigError):
        AppConfig.from_env()


@pytest.mark.parametrize("value", ["0", "33", "abc"])
def test_pool_size_is_bounded(monkeypatch, value):
    set_env(monkeypatch, DB_POOL_SIZE=value)
    with pytest.raises(ConfigError):
        AppConfig.from_env()


def test_missing_variable_is_reported(monkeypatch):
    set_env(monkeypatch)
    monkeypatch.delenv("DB_PASSWORD")
    with pytest.raises(ConfigError, match="DB_PASSWORD"):
        AppConfig.from_env()


def test_password_not_in_repr(monkeypatch):
    set_env(monkeypatch)
    assert "s3cret-value" not in repr(AppConfig.from_env())


def test_retention_defaults_to_twelve_months(monkeypatch):
    set_env(monkeypatch)
    assert AppConfig.from_env().retention_months == 12


@pytest.mark.parametrize("value", ["0", "2", "121", "abc"])
def test_retention_has_a_safe_minimum(monkeypatch, value):
    set_env(monkeypatch, EVENT_RETENTION_MONTHS=value)
    with pytest.raises(ConfigError):
        AppConfig.from_env()
