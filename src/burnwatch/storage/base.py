"""Abstract storage backend interface for BurnWatch.

Provides the contract for persistence implementations (local SQLite and optional AWS).
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from burnwatch.incidents.models import Incident, IncidentStatus
from burnwatch.models.observation import NormalizedObservation


class StorageBackend(ABC):
    """Abstract storage backend interface."""

    @abstractmethod
    def save_observation(
        self, obs: NormalizedObservation
    ) -> tuple[NormalizedObservation, bool]:
        """Save a normalized observation and its quality flags.

        If an observation with the same (device_id, sequence) already exists,
        it is not overwritten; the existing observation is returned.

        Args:
            obs: Normalized observation to persist.

        Returns:
            Tuple of (persisted_observation, is_new).
            is_new is True if newly inserted, False if duplicate.
        """
        ...

    @abstractmethod
    def get_observation(self, observation_id: str) -> NormalizedObservation | None:
        """Retrieve an observation by its unique ID."""
        ...

    @abstractmethod
    def get_observation_by_sequence(
        self, device_id: str, sequence: int
    ) -> NormalizedObservation | None:
        """Retrieve an observation by device_id and sequence number."""
        ...

    @abstractmethod
    def list_observations(
        self,
        device_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[NormalizedObservation], int]:
        """List observations with optional device_id filter and pagination.

        Returns:
            Tuple of (items, total_count).
        """
        ...

    @abstractmethod
    def save_incident(self, incident: Incident) -> None:
        """Save or update an incident and its audit history records."""
        ...

    @abstractmethod
    def get_incident(self, incident_id: str) -> Incident | None:
        """Retrieve an incident with full history by its ID."""
        ...

    @abstractmethod
    def list_incidents(
        self,
        status: IncidentStatus | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[Incident], int]:
        """List incidents with optional status filter and pagination.

        Returns:
            Tuple of (items, total_count).
        """
        ...
