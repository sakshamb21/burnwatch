"""Incident service managing the investigation lifecycle and persistence.

Coordinates incident creation from anomaly detections, status reviews,
and audit trails.
"""

from __future__ import annotations

import logging
from typing import Any

from burnwatch.incidents.models import (
    Incident,
    IncidentHistoryEntry,
    IncidentStatus,
)
from burnwatch.models.observation import NormalizedObservation

logger = logging.getLogger(__name__)


class IncidentService:
    """Service for managing the lifecycle of environmental burning incidents.

    Can operate with an in-memory repository or with a persistent StorageBackend.
    """

    def __init__(self, storage: Any | None = None) -> None:
        self.storage = storage
        self._memory_store: dict[str, Incident] = {}

    def create_candidate_incident(
        self,
        trigger_obs: NormalizedObservation,
        supporting_obs_ids: list[str] | None = None,
    ) -> Incident:
        """Create a new candidate incident from a triggered anomalous observation.

        Args:
            trigger_obs: The observation that met persistence criteria.
            supporting_obs_ids: Optional list of related observation IDs.

        Returns:
            Newly created Incident in CANDIDATE status.
        """
        obs_ids = list(supporting_obs_ids or [])
        if trigger_obs.observation_id not in obs_ids:
            obs_ids.append(trigger_obs.observation_id)

        incident = Incident(
            status=IncidentStatus.CANDIDATE,
            device_id=trigger_obs.device_id,
            source_mode=trigger_obs.source_mode,
            is_simulated=trigger_obs.is_simulated,
            trigger_observation_id=trigger_obs.observation_id,
            latitude=trigger_obs.latitude,
            longitude=trigger_obs.longitude,
            peak_mq135=trigger_obs.mq135_raw,
            peak_anomaly_score=trigger_obs.anomaly_score or 0.0,
            observation_ids=obs_ids,
        )

        # Initial history entry
        incident.history.append(
            IncidentHistoryEntry(
                from_status=IncidentStatus.CANDIDATE,
                to_status=IncidentStatus.CANDIDATE,
                actor="system:detector",
                notes=f"Candidate incident created by detector (score={trigger_obs.anomaly_score})",
            )
        )

        self._save(incident)
        logger.info(
            "Created candidate incident %s (device=%s, simulated=%s)",
            incident.incident_id,
            incident.device_id,
            incident.is_simulated,
        )
        return incident

    def get_incident(self, incident_id: str) -> Incident | None:
        """Retrieve an incident by ID."""
        if self.storage is not None:
            return self.storage.get_incident(incident_id)
        return self._memory_store.get(incident_id)

    def list_incidents(
        self,
        status: IncidentStatus | str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[Incident], int]:
        """List incidents with optional status filter and pagination."""
        status_enum = None
        if status is not None:
            status_enum = (
                status
                if isinstance(status, IncidentStatus)
                else IncidentStatus(str(status))
            )

        if self.storage is not None:
            return self.storage.list_incidents(
                status=status_enum, limit=limit, offset=offset
            )

        filtered = [
            inc
            for inc in self._memory_store.values()
            if status_enum is None or inc.status == status_enum
        ]
        # Sort newest first
        filtered.sort(key=lambda x: x.created_at, reverse=True)
        total = len(filtered)
        paginated = filtered[offset : offset + limit]
        return paginated, total

    def review_incident(
        self,
        incident_id: str,
        action: str,
        reviewer: str,
        notes: str,
    ) -> Incident:
        """Execute a human review action on an incident.

        Actions:
        - 'under_review': Mark incident as under active review.
        - 'confirm': Validate and confirm incident (requires human notes).
        - 'dismiss': Dismiss candidate or under_review incident as false alert.

        Args:
            incident_id: ID of the incident.
            action: Review action ('under_review', 'confirm', 'dismiss').
            reviewer: Name or identifier of human reviewer.
            notes: Review justification notes.

        Returns:
            Updated Incident.

        Raises:
            KeyError: If incident_id is not found.
            InvalidTransitionError: If transition is forbidden.
            ValueError: If action is unknown or inputs invalid.
        """
        incident = self.get_incident(incident_id)
        if incident is None:
            raise KeyError(f"Incident not found: {incident_id}")

        action_clean = action.strip().lower()

        if action_clean == "under_review":
            incident.record_transition(
                IncidentStatus.UNDER_REVIEW, actor=reviewer, notes=notes
            )
        elif action_clean == "confirm":
            # If still candidate, step through under_review to maintain audit trail
            if incident.status == IncidentStatus.CANDIDATE:
                incident.record_transition(
                    IncidentStatus.UNDER_REVIEW,
                    actor=reviewer,
                    notes=f"Opened for review by {reviewer}",
                )
            incident.record_transition(
                IncidentStatus.CONFIRMED, actor=reviewer, notes=notes
            )
        elif action_clean == "dismiss":
            incident.record_transition(
                IncidentStatus.DISMISSED, actor=reviewer, notes=notes
            )
        else:
            raise ValueError(
                f"Unknown review action {action!r}. Must be 'under_review', 'confirm', or 'dismiss'"
            )

        self._save(incident)
        return incident

    def update_status(
        self,
        incident_id: str,
        new_status: IncidentStatus | str,
        actor: str,
        notes: str,
    ) -> Incident:
        """Transition incident status to a new state.

        Args:
            incident_id: ID of the incident.
            new_status: Target IncidentStatus.
            actor: Name or ID of reviewer / operator.
            notes: Explanation notes.

        Returns:
            Updated Incident.

        Raises:
            KeyError: If incident_id is not found.
            InvalidTransitionError: If transition is not allowed.
        """
        incident = self.get_incident(incident_id)
        if incident is None:
            raise KeyError(f"Incident not found: {incident_id}")

        status_enum = (
            new_status
            if isinstance(new_status, IncidentStatus)
            else IncidentStatus(str(new_status))
        )

        incident.record_transition(status_enum, actor=actor, notes=notes)
        self._save(incident)
        return incident

    def _save(self, incident: Incident) -> None:
        if self.storage is not None:
            self.storage.save_incident(incident)
        else:
            self._memory_store[incident.incident_id] = incident
