"""Abstract base class for observation sources.

All data sources (simulator, CanSat adapter) implement this interface
so the downstream pipeline is source-agnostic.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator

from burnwatch.models.observation import RawObservation, SourceMode


class ObservationSource(ABC):
    """Base interface for observation data sources.

    Concrete implementations yield RawObservation records from either
    the deterministic simulator or the CanSat adapter.
    """

    @property
    @abstractmethod
    def source_mode(self) -> SourceMode:
        """Return the source mode for provenance tracking."""

    @abstractmethod
    def observations(self) -> Iterator[RawObservation]:
        """Yield observations from this source.

        Each call produces a fresh iterator. Implementations must handle
        their own error recovery (e.g., malformed lines in JSONL).
        """

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(mode={self.source_mode.value})"
