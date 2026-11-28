import uuid
from datetime import UTC, datetime

import pytest

from eventhub import accounts, routes_events
from eventhub.accounts import Role
from eventhub.reporting import StoredEvent
from tests.conftest import make_user

AUTH = {"Authorization": "Bearer test-token-value"}


def event_payload(**overrides):
    body = {
        "occurred_at": "2026-11-26T12:00:00Z",
        "source": "web-01",
        "event_id": str(uuid.uuid4()),
        "severity": 4,
        "message": "Login failed",
    }
    body.update(overrides)
    return body


def as_user(monkeypatch, role):
    monkeypatch.setattr(accounts, "resolve_session", lambda *a, **k: make_user(role))


def test_ingest_role_can_submit_events(client, monkeypatch):
    as_user(monkeypatch, Role.INGEST)
    seen = {}

    def fake_ingest(conn, events, **kwargs):
        seen["count"], seen["by"] = len(list(events)), kwargs["ingested_by"]
        return seen["count"]

    monkeypatch.setattr(routes_events, "ingest", fake_ingest)
    response = client.post("/events", json={"events": [event_payload()]}, headers=AUTH)
    assert response.status_code == 200
    assert response.json() == {"submitted": 1}
    assert seen == {"count": 1, "by": 1}


def test_reporter_cannot_submit_events(client, monkeypatch):
    as_user(monkeypatch, Role.REPORTER)
    response = client.post("/events", json={"events": [event_payload()]}, headers=AUTH)
    assert response.status_code == 403


def test_ingest_role_cannot_read_events(client, monkeypatch):
    as_user(monkeypatch, Role.INGEST)
    assert client.get("/events", headers=AUTH).status_code == 403


@pytest.mark.parametrize(
    "body",
    [
        {"events": []},
        {"events": [event_payload() for _ in range(1001)]},
        {"events": [event_payload(severity=9)]},
        {"events": [event_payload(source="Bad Source")]},
        {"events": [event_payload(occurred_at="2026-11-26T12:00:00")]},  # naive timestamp
        {"events": [event_payload(extra="x")]},
        {"events": [event_payload(message="   ")]},
    ],
)
def test_invalid_batches_are_rejected(client, monkeypatch, body):
    as_user(monkeypatch, Role.INGEST)
    assert client.post("/events", json=body, headers=AUTH).status_code == 422


def test_reporter_can_query_events(client, monkeypatch):
    as_user(monkeypatch, Role.REPORTER)
    stored = StoredEvent(
        5, datetime(2026, 11, 26, 12, tzinfo=UTC), "web-01", uuid.uuid4(), 4, "Login failed"
    )
    monkeypatch.setattr(routes_events, "list_events", lambda *a, **k: [stored])
    response = client.get("/events?source=web-01&limit=10", headers=AUTH)
    assert response.status_code == 200
    assert response.json()[0]["message"] == "Login failed"


def test_query_parameters_are_bounded(client, monkeypatch):
    as_user(monkeypatch, Role.REPORTER)
    assert client.get("/events?limit=201", headers=AUTH).status_code == 422
    assert client.get("/events?offset=-1", headers=AUTH).status_code == 422
    assert client.get("/events?source=bad%20source", headers=AUTH).status_code == 422


def test_oversized_time_window_is_rejected(client, monkeypatch):
    as_user(monkeypatch, Role.REPORTER)
    url = "/events?since=2026-01-01T00:00:00Z&until=2026-11-26T00:00:00Z"
    assert client.get(url, headers=AUTH).status_code == 422