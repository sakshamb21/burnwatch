"""Integration tests for BurnWatch REST API using TestClient."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from burnwatch.api.app import create_app
from burnwatch.incidents.models import Incident
from burnwatch.incidents.service import IncidentService
from burnwatch.models.observation import SourceMode
from burnwatch.storage.local import LocalStorage


@pytest.fixture
def api_client() -> TestClient:
    """Fixture providing a fresh TestClient backed by in-memory SQLite."""
    storage = LocalStorage(":memory:")
    service = IncidentService(storage=storage)
    app = create_app(storage=storage, incident_service=service)
    return TestClient(app)


class TestHealthEndpoint:
    """Tests for GET /health."""

    def test_health_check_returns_200(self, api_client: TestClient) -> None:
        response = api_client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "version" in data
        assert "data_source" in data
        assert "storage" in data

    def test_frontend_is_served(self, api_client: TestClient) -> None:
        response = api_client.get("/")
        assert response.status_code == 200
        assert "BurnWatch" in response.text

    def test_frontend_assets_are_served(self, api_client: TestClient) -> None:
        response = api_client.get("/static/app.js")
        assert response.status_code == 200
        assert "renderRoute" in response.text
        assert 'source_mode === "cansat" && !item.is_simulated' in response.text
        assert "initialiseLeafletMap" in response.text

    def test_frontend_has_exactly_five_primary_dashboards(
        self, api_client: TestClient
    ) -> None:
        response = api_client.get("/")
        assert response.status_code == 200
        assert response.text.count('data-route="') == 5
        for title in (
            "Incident Map",
            "Event Evidence",
            "Community Reports",
            "Investigation Workflow",
            "Impact Report",
        ):
            assert title in response.text
        assert "Administrator sign in" in response.text
        assert "OpenStreetMap" in response.text

    def test_delhi_dashboard_sample_has_five_complete_device_series(self) -> None:
        sample_path = Path(__file__).parents[2] / "data" / "demo" / "delhi_cansat_dashboard_sample.jsonl"
        rows = [json.loads(line) for line in sample_path.read_text(encoding="utf-8").splitlines()]
        counts = Counter(row["device_id"] for row in rows)

        assert len(rows) == 250
        assert len(counts) == 5
        assert set(counts.values()) == {50}
        assert all(row["gps_fix"] is True for row in rows)


class TestObservationEndpoints:
    """Tests for POST and GET /observations."""

    def test_submit_observation_valid(
        self, api_client: TestClient, canonical_obs: dict
    ) -> None:
        response = api_client.post("/observations", json=canonical_obs)
        assert response.status_code == 201
        data = response.json()
        assert "observation_id" in data
        assert data["status"] == "accepted"
        assert "anomaly_detected" in data
        assert "quality_flags" in data

    def test_submit_observation_idempotent(
        self, api_client: TestClient, canonical_obs: dict
    ) -> None:
        # First submission
        res1 = api_client.post("/observations", json=canonical_obs)
        assert res1.status_code == 201
        obs_id = res1.json()["observation_id"]

        # Duplicate submission (same device and sequence)
        res2 = api_client.post("/observations", json=canonical_obs)
        assert res2.status_code == 200
        data2 = res2.json()
        assert data2["observation_id"] == obs_id
        assert data2["status"] == "duplicate_accepted"

    def test_submit_observation_validation_error(
        self, api_client: TestClient, canonical_obs: dict
    ) -> None:
        bad_obs = dict(canonical_obs)
        bad_obs["latitude"] = 95.0  # Invalid latitude > 90
        response = api_client.post("/observations", json=bad_obs)
        assert response.status_code == 422
        data = response.json()
        assert "detail" in data

    def test_list_observations(
        self, api_client: TestClient, canonical_obs: dict
    ) -> None:
        # Ingest 3 observations
        for i in range(1, 4):
            api_client.post(
                "/observations",
                json={**canonical_obs, "sequence": i, "device_time_ms": i * 1000},
            )

        response = api_client.get("/observations?limit=2&offset=0")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 3
        assert len(data["items"]) == 2


class TestIncidentEndpoints:
    """Tests for incident inspection, review, and status transitions."""

    def test_get_incident_not_found(self, api_client: TestClient) -> None:
        response = api_client.get("/incidents/nonexistent-id")
        assert response.status_code == 404
        assert response.json()["detail"] == "Incident not found"

    def test_review_simulated_incident_confirm_rejected_with_409(
        self, api_client: TestClient, canonical_obs: dict
    ) -> None:
        # 1. Ingest observation that creates simulated candidate incident
        # We inject a simulated incident into storage directly for testing
        storage = LocalStorage(":memory:")
        service = IncidentService(storage=storage)
        app = create_app(storage=storage, incident_service=service)
        client = TestClient(app)

        inc = Incident(
            device_id="sim-01",
            source_mode=SourceMode.SIMULATED,
            is_simulated=True,
            trigger_observation_id="obs-1",
            peak_mq135=800,
            peak_anomaly_score=6.0,
        )
        storage.save_incident(inc)

        # Attempt to confirm simulated incident
        resp = client.post(
            f"/incidents/{inc.incident_id}/review",
            json={
                "action": "confirm",
                "reviewer": "officer_1",
                "notes": "Testing confirmation",
            },
        )
        assert resp.status_code == 409
        assert "Simulated incidents cannot be confirmed" in resp.json()["detail"]

    def test_review_cansat_incident_dismiss_success(
        self, api_client: TestClient
    ) -> None:
        storage = LocalStorage(":memory:")
        service = IncidentService(storage=storage)
        app = create_app(storage=storage, incident_service=service)
        client = TestClient(app)

        inc = Incident(
            device_id="cansat-01",
            source_mode=SourceMode.CANSAT,
            trigger_observation_id="obs-1",
            peak_mq135=600,
            peak_anomaly_score=4.0,
        )
        storage.save_incident(inc)

        resp = client.post(
            f"/incidents/{inc.incident_id}/review",
            json={
                "action": "dismiss",
                "reviewer": "officer_1",
                "notes": "Dismissing false alarm",
            },
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "dismissed"

    def test_review_cansat_incident_confirm_success(
        self, api_client: TestClient
    ) -> None:
        storage = LocalStorage(":memory:")
        service = IncidentService(storage=storage)
        app = create_app(storage=storage, incident_service=service)
        client = TestClient(app)

        inc = Incident(
            device_id="cansat-01",
            source_mode=SourceMode.CANSAT,
            trigger_observation_id="obs-1",
            peak_mq135=600,
            peak_anomaly_score=4.0,
        )
        storage.save_incident(inc)

        resp = client.post(
            f"/incidents/{inc.incident_id}/review",
            json={
                "action": "confirm",
                "reviewer": "officer_1",
                "notes": "Confirmed by ground team",
            },
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "confirmed"

    def test_community_report_submission(self, api_client: TestClient) -> None:
        resp = api_client.post(
            "/reports",
            json={
                "reporter_name": "Citizen John",
                "description": "Thick black smoke rising from empty plot",
                "contact": "555-0199",
                "latitude": 28.71,
                "longitude": 77.11,
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert "report_id" in data
        assert data["status"] == "submitted"
