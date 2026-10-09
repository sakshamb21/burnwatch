"""Integration tests for LocalStorage (SQLite)."""

from __future__ import annotations

import uuid
from pathlib import Path

from burnwatch.incidents.models import (
    Incident,
    IncidentStatus,
)
from burnwatch.models.observation import (
    NormalizedObservation,
    QualityFlag,
    RawObservation,
    SourceMode,
)
from burnwatch.storage.local import LocalStorage


def _make_obs(
    seq: int = 1,
    device_id: str = "cansat-01",
    flags: list[QualityFlag] | None = None,
) -> NormalizedObservation:
    raw = RawObservation(
        device_id=device_id,
        sequence=seq,
        device_time_ms=seq * 1000,
        mq135_raw=350,
        latitude=28.61,
        longitude=77.23,
        gps_fix=True,
        satellites=7,
    )
    obs = NormalizedObservation.from_raw(raw, SourceMode.CANSAT)
    if flags:
        obs.quality_flags = list(flags)
    return obs


class TestLocalStorageObservations:
    """Tests for observation storage and idempotency in SQLite."""

    def test_save_and_retrieve_observation(self) -> None:
        db = LocalStorage(":memory:")
        obs = _make_obs(seq=10, flags=[QualityFlag.LOW_SATELLITES, QualityFlag.WARMUP])

        saved_obs, is_new = db.save_observation(obs)
        assert is_new is True
        assert saved_obs.observation_id == obs.observation_id

        fetched = db.get_observation(obs.observation_id)
        assert fetched is not None
        assert fetched.device_id == "cansat-01"
        assert fetched.sequence == 10
        assert QualityFlag.LOW_SATELLITES in fetched.quality_flags
        assert QualityFlag.WARMUP in fetched.quality_flags

    def test_duplicate_prevention_idempotent(self) -> None:
        db = LocalStorage(":memory:")
        obs1 = _make_obs(seq=5)
        saved1, is_new1 = db.save_observation(obs1)
        assert is_new1 is True

        # Second observation with same device and sequence
        obs2 = _make_obs(seq=5)
        obs2.observation_id = str(uuid.uuid4())
        obs2.mq135_raw = 999  # Different payload
        saved2, is_new2 = db.save_observation(obs2)

        # Should NOT create duplicate; returns original record
        assert is_new2 is False
        assert saved2.observation_id == obs1.observation_id
        assert saved2.mq135_raw == 350

        # Verify only 1 observation in total
        items, total = db.list_observations()
        assert total == 1

    def test_persistence_across_restart(self, tmp_path: Path) -> None:
        db_path = tmp_path / "test_persist.db"
        # Session 1: Write observation
        db1 = LocalStorage(db_path)
        obs = _make_obs(seq=42)
        db1.save_observation(obs)
        db1.close()

        # Session 2: Reopen and read
        db2 = LocalStorage(db_path)
        fetched = db2.get_observation(obs.observation_id)
        assert fetched is not None
        assert fetched.sequence == 42
        db2.close()

    def test_list_observations_filtering_and_pagination(self) -> None:
        db = LocalStorage(":memory:")
        for seq in range(1, 11):
            db.save_observation(_make_obs(seq=seq, device_id="dev-A"))
        for seq in range(1, 6):
            db.save_observation(_make_obs(seq=seq, device_id="dev-B"))

        # Test device filter
        items_a, total_a = db.list_observations(device_id="dev-A")
        assert total_a == 10
        assert len(items_a) == 10

        items_b, total_b = db.list_observations(device_id="dev-B")
        assert total_b == 5
        assert len(items_b) == 5

        # Test pagination
        page, total = db.list_observations(device_id="dev-A", limit=4, offset=2)
        assert total == 10
        assert len(page) == 4


class TestLocalStorageIncidents:
    """Tests for incident storage, status transitions, and history in SQLite."""

    def test_save_and_retrieve_incident_with_history(self) -> None:
        db = LocalStorage(":memory:")
        obs = _make_obs(seq=1)
        db.save_observation(obs)

        inc = Incident(
            device_id="cansat-01",
            source_mode=SourceMode.CANSAT,
            trigger_observation_id=obs.observation_id,
            peak_mq135=720,
            peak_anomaly_score=5.2,
            observation_ids=[obs.observation_id],
        )
        inc.record_transition(
            IncidentStatus.UNDER_REVIEW, actor="officer_1", notes="Reviewing anomaly"
        )
        db.save_incident(inc)

        fetched = db.get_incident(inc.incident_id)
        assert fetched is not None
        assert fetched.status == IncidentStatus.UNDER_REVIEW
        assert fetched.peak_mq135 == 720
        assert len(fetched.history) == 1
        assert fetched.history[0].actor == "officer_1"
        assert obs.observation_id in fetched.observation_ids

    def test_update_incident_status_persisted(self) -> None:
        db = LocalStorage(":memory:")
        inc = Incident(
            device_id="cansat-01",
            source_mode=SourceMode.CANSAT,
            trigger_observation_id="obs-1",
            peak_mq135=600,
            peak_anomaly_score=4.0,
        )
        db.save_incident(inc)

        # Transition and update
        inc.record_transition(
            IncidentStatus.UNDER_REVIEW, actor="reviewer", notes="Starting review"
        )
        inc.record_transition(
            IncidentStatus.CONFIRMED, actor="reviewer", notes="Smoke detected"
        )
        db.save_incident(inc)

        fetched = db.get_incident(inc.incident_id)
        assert fetched is not None
        assert fetched.status == IncidentStatus.CONFIRMED
        assert len(fetched.history) == 2

    def test_community_report_persistence(self) -> None:
        db = LocalStorage(":memory:")
        rep = db.save_community_report(
            report_id="rep-1",
            reporter_name="Citizen Jane",
            description="Dense smoke noticed near west field",
            contact="jane@example.com",
            latitude=28.62,
            longitude=77.21,
        )
        assert rep["report_id"] == "rep-1"
        assert rep["status"] == "submitted"
