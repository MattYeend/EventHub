import pytest

from eventhub import accounts
from eventhub.accounts import AuthenticationError, Role, User
from tests.conftest import make_user

AUTH = {"Authorization": "Bearer test-token-value"}
NEW_USER = {"username": "bob.smith", "password": "a-very-long-passphrase", "role": "reporter"}


def as_user(monkeypatch, user: User | None) -> None:
    monkeypatch.setattr(accounts, "resolve_session", lambda *args, **kwargs: user)


def test_health_needs_no_authentication(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_security_headers_are_set(client):
    response = client.get("/health")
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["Referrer-Policy"] == "no-referrer"


def test_interactive_docs_are_off_by_default(client):
    assert client.get("/docs").status_code == 404
    assert client.get("/openapi.json").status_code == 404


def test_missing_token_is_rejected(client):
    response = client.get("/me")
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"


def test_unknown_or_expired_token_is_rejected(client, monkeypatch):
    as_user(monkeypatch, None)
    assert client.get("/me", headers=AUTH).status_code == 401


def test_me_returns_the_current_user_without_secrets(client, monkeypatch):
    as_user(monkeypatch, make_user(Role.REPORTER))
    body = client.get("/me", headers=AUTH).json()
    assert body["username"] == "alice" and body["role"] == "reporter"
    assert "password_hash" not in str(body)
    assert set(body) == {"id", "username", "role", "is_active", "must_change_password"}


def test_login_failure_is_generic(client, monkeypatch):
    def reject(*args, **kwargs):
        raise AuthenticationError

    monkeypatch.setattr(accounts, "authenticate", reject)
    response = client.post("/auth/login", json={"username": "alice", "password": "nope"})
    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid credentials"}


def test_login_rejects_unknown_fields(client):
    body = {"username": "alice", "password": "x", "admin": True}
    assert client.post("/auth/login", json=body).status_code == 422


def test_login_issues_a_bearer_token(client, monkeypatch):
    monkeypatch.setattr(accounts, "authenticate", lambda *a, **k: make_user(Role.INGEST))
    monkeypatch.setattr(accounts, "create_session", lambda conn, uid, ttl, now: ("tok", now + ttl))
    body = client.post("/auth/login", json={"username": "alice", "password": "x"}).json()
    assert body["access_token"] == "tok"
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == 3600
    assert body["must_change_password"] is False


@pytest.mark.parametrize("role", [Role.REPORTER, Role.INGEST])
def test_only_admins_can_manage_users(client, monkeypatch, role):
    as_user(monkeypatch, make_user(role))
    assert client.post("/users", json=NEW_USER, headers=AUTH).status_code == 403
    assert client.get("/users", headers=AUTH).status_code == 403
    assert client.patch("/users/2", json={"is_active": False}, headers=AUTH).status_code == 403


def test_password_change_is_enforced_before_any_other_action(client, monkeypatch):
    as_user(monkeypatch, make_user(Role.ADMIN, must_change=True))
    response = client.get("/users", headers=AUTH)
    assert response.status_code == 403
    assert response.json() == {"detail": "Password change required"}
    assert client.get("/me", headers=AUTH).status_code == 200


def test_admin_can_create_a_user(client, monkeypatch):
    as_user(monkeypatch, make_user(Role.ADMIN))
    created = User(2, "bob.smith", Role.REPORTER, True, True)
    monkeypatch.setattr(accounts, "create_user", lambda *a, **k: created)
    response = client.post("/users", json=NEW_USER, headers=AUTH)
    assert response.status_code == 201
    assert response.json()["username"] == "bob.smith"
    assert "password_hash" not in response.text
    assert "a-very-long-passphrase" not in response.text


def test_unknown_role_is_rejected(client, monkeypatch):
    as_user(monkeypatch, make_user(Role.ADMIN))
    response = client.post("/users", json={**NEW_USER, "role": "root"}, headers=AUTH)
    assert response.status_code == 422


def test_duplicate_username_maps_to_409(client, monkeypatch):
    as_user(monkeypatch, make_user(Role.ADMIN))

    def duplicate(*args, **kwargs):
        raise accounts.DuplicateUserError("bob.smith")

    monkeypatch.setattr(accounts, "create_user", duplicate)
    assert client.post("/users", json=NEW_USER, headers=AUTH).status_code == 409


def test_weak_password_maps_to_422(client, monkeypatch):
    as_user(monkeypatch, make_user(Role.ADMIN))
    response = client.post("/users", json={**NEW_USER, "password": "short"}, headers=AUTH)
    assert response.status_code == 422


def test_last_admin_protection_maps_to_409(client, monkeypatch):
    as_user(monkeypatch, make_user(Role.ADMIN))

    def refuse(*args, **kwargs):
        raise accounts.LastAdminError(1)

    monkeypatch.setattr(accounts, "update_user", refuse)
    response = client.patch("/users/1", json={"is_active": False}, headers=AUTH)
    assert response.status_code == 409


def test_update_requires_at_least_one_field(client, monkeypatch):
    as_user(monkeypatch, make_user(Role.ADMIN))
    assert client.patch("/users/2", json={}, headers=AUTH).status_code == 422


def test_missing_user_maps_to_404(client, monkeypatch):
    as_user(monkeypatch, make_user(Role.ADMIN))
    monkeypatch.setattr(accounts, "get_user", lambda *a, **k: None)
    assert client.get("/users/99", headers=AUTH).status_code == 404
