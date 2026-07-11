from __future__ import annotations

import datetime

from fastapi.testclient import TestClient

from app.api import routes
from app.main import create_app


LEVELS = {
    "2026-07-13": {"call_wall": 6300.0, "flip": 6250.5, "put_wall": 6200.0},
    "2026-07-17": {"call_wall": 6400.0, "flip": None, "put_wall": 6100.0},
}


def _client(monkeypatch) -> TestClient:
    async def fake_get_bundle(_request):
        return {"levels": LEVELS}, {}

    monkeypatch.setattr(routes, "_get_bundle", fake_get_bundle)
    monkeypatch.setattr(routes.market, "today_expiry_date",
                        lambda: datetime.date(2026, 7, 12))
    return TestClient(create_app(include_mcp=False))


def test_levels_accepts_single_integer(monkeypatch):
    with _client(monkeypatch) as client:
        response = client.get("/api/spx/levels", params={"dte": "1"})

    assert response.status_code == 200
    assert response.json() == {
        "dte": 1, "expiry": "2026-07-13", "available": True,
        "call_wall": 6300.0, "flip": 6250.5, "put_wall": 6200.0,
    }


def test_levels_accepts_repeated_dates_and_returns_array(monkeypatch):
    with _client(monkeypatch) as client:
        response = client.get(
            "/api/spx/levels",
            params=[("dte", "2026-07-13"), ("dte", "2026-07-17")],
        )

    assert response.status_code == 200
    body = response.json()
    assert [item["dte"] for item in body] == [1, 5]
    assert body[1]["expiry"] == "2026-07-17"
    assert body[1]["flip"] is None


def test_levels_accepts_json_array_and_marks_missing_expiry(monkeypatch):
    with _client(monkeypatch) as client:
        response = client.get("/api/spx/levels", params={"dte": "[1, 2]"})

    assert response.status_code == 200
    assert response.json()[1] == {
        "dte": 2, "expiry": "2026-07-14", "available": False,
        "call_wall": None, "flip": None, "put_wall": None,
    }


def test_levels_rejects_invalid_or_past_values(monkeypatch):
    with _client(monkeypatch) as client:
        invalid = client.get("/api/spx/levels", params={"dte": "tomorrow"})
        past = client.get("/api/spx/levels", params={"dte": "2026-07-11"})

    assert invalid.status_code == 422
    assert past.status_code == 422
