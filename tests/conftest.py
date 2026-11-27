import pytest
from fastapi.testclient import TestClient

from eventhub import api
from eventhub.accounts import Role, User
from eventhub.config import AppConfig, DbConfig
from eventhub.deps import get_conn


@pytest.fixture
def app_config() -> AppConfig:
    return AppConfig(
        environment="development",
        session_ttl_minutes=60,
        enable_docs=False,
        db=DbConfig(
            host="localhost",
            port=3306,
            user="app",
            database="eventhub",
            ssl_ca=None,
            ssl_verify=False,
            pool_size=2,
            password="s3cret",
        ),
    )


@pytest.fixture
def client(app_config: AppConfig) -> TestClient:
    """API client with the database dependency replaced, so no live database is needed."""
    app = api.create_app(app_config)

    def fake_connection():
        yield object()

    app.dependency_overrides[get_conn] = fake_connection
    return TestClient(app)


def make_user(role: Role = Role.ADMIN, *, must_change: bool = False, user_id: int = 1) -> User:
    return User(
        id=user_id,
        username="alice",
        role=role,
        is_active=True,
        must_change_password=must_change,
    )
