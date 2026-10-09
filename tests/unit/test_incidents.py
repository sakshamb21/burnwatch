"""Unit tests for incident domain models, state machine transitions, and service."""

from __future__ import annotations

import pytest

from burnwatch.incidents.models import (
    Incident,
    IncidentStatus,
    InvalidTransitionError,
)
from burnwatch.incidents.service import IncidentService
from burnwatch.models.observation import (
    NormalizedObservation,
    RawObservation,
    SourceMode,
)


def _make_sample_obs(
    source_mode: SourceMode = SourceMode.CANSAT,
    score: float = 4.5,
) -> NormalizedObservation:
    raw = RawObservation(
        device_id="cansat-01",
        sequence=100,
        device_time_ms=200000,
        mq135_raw=650,
        latitude=28.7041,
        longitude=77.1025,
        gps_fix=True,
        satellites=8,
    )
    obs = NormalizedObservation.from_raw(raw, source_mode=source_mode)
    obs.anomaly_detected = True
    obs.anomaly_score = score
    return obs


class TestIncidentStateMachine:
    """Tests for Incident state transitions and business rules."""

    def test_new_incident_defaults(self) -> None:
        inc = Incident(
            device_id="cansat-01",
            source_mode=SourceMode.CANSAT,
            trigger_observation_id="obs-1",
            peak_mq135=600,
            peak_anomaly_score=4.2,
        )
        assert inc.status == IncidentStatus.CANDIDATE
        assert inc.history == []

    def test_valid_full_lifecycle(self) -> None:
        inc = Incident(
            device_id="cansat-01",
            source_mode=SourceMode.CANSAT,
            trigger_observation_id="obs-1",
            peak_mq135=600,
            peak_anomaly_score=4.2,
        )
        # 1. Candidate -> Under Review
        entry1 = inc.record_transition(
            IncidentStatus.UNDER_REVIEW,
            actor="officer_alice",
            notes="Starting investigation",
        )
        assert inc.status == IncidentStatus.UNDER_REVIEW
        assert entry1.from_status == IncidentStatus.CANDIDATE
        assert entry1.to_status == IncidentStatus.UNDER_REVIEW

        # 2. Under Review -> Confirmed
        inc.record_transition(
            IncidentStatus.CONFIRMED,
            actor="officer_alice",
            notes="Confirmed waste burning via patrol unit",
        )
        assert inc.status == IncidentStatus.CONFIRMED

        # 3. Confirmed -> Resolved
        inc.record_transition(
            IncidentStatus.RESOLVED,
            actor="officer_bob",
            notes="Fire extinguished by team",
        )
        assert inc.status == IncidentStatus.RESOLVED

        # 4. Resolved -> Monitoring
        inc.record_transition(
            IncidentStatus.MONITORING,
            actor="officer_bob",
            notes="Monitoring for reignition",
        )
        assert inc.status == IncidentStatus.MONITORING

        # 5. Monitoring -> Resolved
        inc.record_transition(
            IncidentStatus.RESOLVED,
            actor="officer_bob",
            notes="No reignition observed for 24h",
        )
        assert inc.status == IncidentStatus.RESOLVED

        # Verify audit history
        assert len(inc.history) == 5
        assert [h.to_status for h in inc.history] == [
            IncidentStatus.UNDER_REVIEW,
            IncidentStatus.CONFIRMED,
            IncidentStatus.RESOLVED,
            IncidentStatus.MONITORING,
            IncidentStatus.RESOLVED,
        ]

    def test_dismiss_from_candidate(self) -> None:
        inc = Incident(
            device_id="cansat-01",
            source_mode=SourceMode.CANSAT,
            trigger_observation_id="obs-1",
            peak_mq135=600,
            peak_anomaly_score=4.2,
        )
        inc.record_transition(
            IncidentStatus.DISMISSED,
            actor="reviewer_1",
            notes="False alarm due to nearby generator exhaust",
        )
        assert inc.status == IncidentStatus.DISMISSED

    def test_dismiss_from_under_review(self) -> None:
        inc = Incident(
            device_id="cansat-01",
            source_mode=SourceMode.CANSAT,
            trigger_observation_id="obs-1",
            peak_mq135=600,
            peak_anomaly_score=4.2,
        )
        inc.record_transition(
            IncidentStatus.UNDER_REVIEW, actor="officer_1", notes="Reviewing"
        )
        inc.record_transition(
            IncidentStatus.DISMISSED,
            actor="officer_1",
            notes="No evidence found on site",
        )
        assert inc.status == IncidentStatus.DISMISSED

    def test_direct_candidate_to_confirmed_rejected(self) -> None:
        inc = Incident(
            device_id="cansat-01",
            source_mode=SourceMode.CANSAT,
            trigger_observation_id="obs-1",
            peak_mq135=600,
            peak_anomaly_score=4.2,
        )
        with pytest.raises(InvalidTransitionError):
            inc.record_transition(
                IncidentStatus.CONFIRMED,
                actor="officer_1",
                notes="Skipping review",
            )

    def test_simulated_data_cannot_be_confirmed(self) -> None:
        inc = Incident(
            device_id="sim-01",
            source_mode=SourceMode.SIMULATED,
            is_simulated=True,
            trigger_observation_id="obs-sim",
            peak_mq135=800,
            peak_anomaly_score=5.0,
        )
        inc.record_transition(
            IncidentStatus.UNDER_REVIEW, actor="officer_1", notes="Checking"
        )
        with pytest.raises(
            InvalidTransitionError, match="Simulated incidents cannot be confirmed"
        ):
            inc.record_transition(
                IncidentStatus.CONFIRMED,
                actor="officer_1",
                notes="Attempt to confirm synthetic data",
            )

    def test_dismissed_cannot_transition(self) -> None:
        inc = Incident(
            device_id="cansat-01",
            source_mode=SourceMode.CANSAT,
            trigger_observation_id="obs-1",
            peak_mq135=600,
            peak_anomaly_score=4.2,
        )
        inc.record_transition(
            IncidentStatus.DISMISSED, actor="officer_1", notes="Dismissed"
        )
        with pytest.raises(InvalidTransitionError):
            inc.record_transition(
                IncidentStatus.UNDER_REVIEW, actor="officer_1", notes="Reopen"
            )

    def test_blank_actor_or_notes_rejected(self) -> None:
        inc = Incident(
            device_id="cansat-01",
            source_mode=SourceMode.CANSAT,
            trigger_observation_id="obs-1",
            peak_mq135=600,
            peak_anomaly_score=4.2,
        )
        with pytest.raises(ValueError, match="Actor/reviewer"):
            inc.record_transition(
                IncidentStatus.UNDER_REVIEW, actor="", notes="Valid notes"
            )

        with pytest.raises(ValueError, match="Notes are required"):
            inc.record_transition(
                IncidentStatus.UNDER_REVIEW, actor="officer", notes="   "
            )


class TestIncidentService:
    """Tests for IncidentService operations."""

    def test_create_candidate_incident(self) -> None:
        service = IncidentService()
        obs = _make_sample_obs()
        inc = service.create_candidate_incident(obs)

        assert inc.status == IncidentStatus.CANDIDATE
        assert inc.device_id == "cansat-01"
        assert inc.trigger_observation_id == obs.observation_id
        assert obs.observation_id in inc.observation_ids
        assert len(inc.history) == 1
        assert inc.history[0].actor == "system:detector"

    def test_review_confirm_workflow(self) -> None:
        service = IncidentService()
        obs = _make_sample_obs(source_mode=SourceMode.CANSAT)
        inc = service.create_candidate_incident(obs)

        # Review action 'confirm' handles stepping through under_review
        updated = service.review_incident(
            incident_id=inc.incident_id,
            action="confirm",
            reviewer="officer_dave",
            notes="Field team verified smoke column",
        )
        assert updated.status == IncidentStatus.CONFIRMED
        assert updated.reviewer == "officer_dave"

    def test_review_dismiss_workflow(self) -> None:
        service = IncidentService()
        obs = _make_sample_obs(source_mode=SourceMode.CANSAT)
        inc = service.create_candidate_incident(obs)

        updated = service.review_incident(
            incident_id=inc.incident_id,
            action="dismiss",
            reviewer="officer_dave",
            notes="Barbecue reported at location",
        )
        assert updated.status == IncidentStatus.DISMISSED

    def test_list_and_filter_incidents(self) -> None:
        service = IncidentService()
        obs1 = _make_sample_obs()
        inc1 = service.create_candidate_incident(obs1)

        obs2 = _make_sample_obs()
        inc2 = service.create_candidate_incident(obs2)
        service.review_incident(inc2.incident_id, "dismiss", "rev", "dismissed")

        candidates, total = service.list_incidents(status=IncidentStatus.CANDIDATE)
        assert total == 1
        assert candidates[0].incident_id == inc1.incident_id

        dismissed, total = service.list_incidents(status="dismissed")
        assert total == 1
        assert dismissed[0].incident_id == inc2.incident_id

        all_inc, total = service.list_incidents()
        assert total == 2
