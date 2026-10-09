"""Incident domain models and state machine.

Defines the incident lifecycle for suspected burning events, state transition
rules, validation constraints, and immutable audit history.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import Enum

from pydantic import BaseModel, Field

from burnwatch.models.observation import SourceMode


class IncidentStatus(str, Enum):
    """Lifecycle statuses for a BurnWatch incident."""

    CANDIDATE = "candidate"
    UNDER_REVIEW = "under_review"
    CONFIRMED = "confirmed"
    DISMISSED = "dismissed"
    RESOLVED = "resolved"
    MONITORING = "monitoring"


ALLOWED_TRANSITIONS: dict[IncidentStatus, set[IncidentStatus]] = {
    IncidentStatus.CANDIDATE: {
        IncidentStatus.UNDER_REVIEW,
        IncidentStatus.DISMISSED,
    },
    IncidentStatus.UNDER_REVIEW: {
        IncidentStatus.CONFIRMED,
        IncidentStatus.DISMISSED,
    },
    IncidentStatus.CONFIRMED: {
        IncidentStatus.RESOLVED,
    },
    IncidentStatus.RESOLVED: {
        IncidentStatus.MONITORING,
    },
    IncidentStatus.MONITORING: {
        IncidentStatus.RESOLVED,
        IncidentStatus.CANDIDATE,
    },
    IncidentStatus.DISMISSED: set(),
}


class InvalidTransitionError(Exception):
    """Raised when an illegal incident status transition is requested."""

    def __init__(
        self, from_status: IncidentStatus, to_status: IncidentStatus, reason: str = ""
    ) -> None:
        msg = f"Cannot transition incident from {from_status.value!r} to {to_status.value!r}"
        if reason:
            msg += f": {reason}"
        super().__init__(msg)
        self.from_status = from_status
        self.to_status = to_status
        self.reason = reason


class IncidentHistoryEntry(BaseModel):
    """Immutable audit record for an incident status transition."""

    entry_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    from_status: IncidentStatus
    to_status: IncidentStatus
    actor: str = Field(
        ..., min_length=1, description="Person or service requesting transition"
    )
    notes: str = Field(
        ..., min_length=1, description="Reason or observation notes for transition"
    )


class Incident(BaseModel):
    """Incident tracking domain model representing a potential burning event."""

    incident_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    status: IncidentStatus = IncidentStatus.CANDIDATE
    device_id: str = Field(..., min_length=1)
    source_mode: SourceMode
    is_simulated: bool = False
    trigger_observation_id: str = Field(..., min_length=1)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    latitude: float | None = None
    longitude: float | None = None
    peak_mq135: int = Field(..., ge=0, le=1023)
    peak_anomaly_score: float = Field(..., ge=0.0)
    observation_ids: list[str] = Field(default_factory=list)
    reviewer: str | None = None
    notes: str | None = None
    history: list[IncidentHistoryEntry] = Field(default_factory=list)

    def can_transition_to(self, new_status: IncidentStatus) -> bool:
        """Check if transition to new_status is structurally allowed."""
        return new_status in ALLOWED_TRANSITIONS.get(self.status, set())

    def record_transition(
        self,
        new_status: IncidentStatus,
        actor: str,
        notes: str,
    ) -> IncidentHistoryEntry:
        """Perform and record a state transition.

        Enforces transition validity and simulation isolation rules.

        Args:
            new_status: Desired new IncidentStatus.
            actor: Name or ID of reviewer or automated system.
            notes: Mandatory transition explanation notes.

        Raises:
            InvalidTransitionError: If the transition violates state rules
                                    or attempts to confirm simulated data.
        """
        # Validate allowed transition
        if not self.can_transition_to(new_status):
            raise InvalidTransitionError(
                self.status,
                new_status,
                f"Allowed transitions from {self.status.value}: "
                f"{[s.value for s in ALLOWED_TRANSITIONS.get(self.status, set())]}",
            )

        # Enforce: Simulated observations cannot produce confirmed incidents
        if new_status == IncidentStatus.CONFIRMED and (
            self.is_simulated or self.source_mode == SourceMode.SIMULATED
        ):
            raise InvalidTransitionError(
                self.status,
                new_status,
                "Simulated incidents cannot be confirmed. Simulated data is for testing only.",
            )

        # Enforce non-empty actor and notes
        if not actor or not actor.strip():
            raise ValueError("Actor/reviewer name is required for transition")
        if not notes or not notes.strip():
            raise ValueError("Notes are required for transition")

        old_status = self.status
        self.status = new_status
        self.updated_at = datetime.now(UTC)
        self.reviewer = actor.strip()
        self.notes = notes.strip()

        entry = IncidentHistoryEntry(
            from_status=old_status,
            to_status=new_status,
            actor=actor.strip(),
            notes=notes.strip(),
        )
        self.history.append(entry)
        return entry
