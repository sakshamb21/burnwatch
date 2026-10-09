"""Observation processing pipeline for BurnWatch.

Coordinates normalization, data quality gating, anomaly detection,
incident candidate triggering, and idempotent persistence.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from burnwatch.detection.anomaly import AnomalyDetectionResult, AnomalyDetector
from burnwatch.incidents.models import Incident
from burnwatch.incidents.service import IncidentService
from burnwatch.ingestion.parser import parse_json_line, parse_jsonl_file
from burnwatch.models.observation import (
    NormalizedObservation,
    QualityFlag,
    RawObservation,
    SourceMode,
)
from burnwatch.quality.checks import QualityChecker
from burnwatch.sources.base import ObservationSource
from burnwatch.storage.base import StorageBackend
from burnwatch.storage.local import LocalStorage

logger = logging.getLogger(__name__)


@dataclass
class PipelineResult:
    """Outcome of processing a single observation."""

    observation: NormalizedObservation
    is_new: bool
    quality_flags: list[QualityFlag]
    anomaly_result: AnomalyDetectionResult
    candidate_incident: Incident | None = None


@dataclass
class PipelineSummary:
    """Aggregated statistics from running a batch or stream through the pipeline."""

    total_received: int = 0
    new_observations: int = 0
    duplicates: int = 0
    anomalies_detected: int = 0
    incidents_created: int = 0
    quality_flag_counts: dict[str, int] = field(default_factory=dict)

    def record(self, result: PipelineResult) -> None:
        self.total_received += 1
        if result.is_new:
            self.new_observations += 1
        else:
            self.duplicates += 1

        if result.observation.anomaly_detected:
            self.anomalies_detected += 1

        if result.candidate_incident is not None:
            self.incidents_created += 1

        for flag in result.quality_flags:
            self.quality_flag_counts[flag.value] = (
                self.quality_flag_counts.get(flag.value, 0) + 1
            )


class PipelineProcessor:
    """Pipeline coordinator for BurnWatch observations.

    Args:
        storage: Persistent or in-memory StorageBackend.
        incident_service: IncidentService instance.
        quality_checker: QualityChecker instance.
        anomaly_detector: AnomalyDetector instance.
        source_mode: Default SourceMode for ingested records.
    """

    def __init__(
        self,
        storage: StorageBackend | None = None,
        incident_service: IncidentService | None = None,
        quality_checker: QualityChecker | None = None,
        anomaly_detector: AnomalyDetector | None = None,
        source_mode: SourceMode = SourceMode.SIMULATED,
    ) -> None:
        self.storage = storage or LocalStorage(":memory:")
        self.incident_service = incident_service or IncidentService(
            storage=self.storage
        )
        self.quality_checker = quality_checker or QualityChecker()
        self.anomaly_detector = anomaly_detector or AnomalyDetector()
        self.source_mode = source_mode

    def process_raw(
        self,
        raw: RawObservation,
        raw_payload: str | None = None,
        source_mode: SourceMode | None = None,
    ) -> PipelineResult:
        """Process a validated RawObservation through the entire pipeline.

        1. Normalizes the observation
        2. Applies quality checks
        3. Evaluates relative MQ135 anomalies
        4. Persists idempotently
        5. Triggers candidate incidents on persistent anomalies
        """
        mode = source_mode or self.source_mode

        # 1. Normalize
        obs = NormalizedObservation.from_raw(
            raw=raw, source_mode=mode, raw_payload=raw_payload
        )

        # 2. Quality checks
        flags = self.quality_checker.check(obs)

        # 3. Anomaly detection
        anomaly_res = self.anomaly_detector.process(obs)

        # 4. Storage (idempotent)
        persisted_obs, is_new = self.storage.save_observation(obs)

        # 5. Incident triggering
        candidate_incident = None
        if anomaly_res.is_candidate_incident and is_new:
            candidate_incident = self.incident_service.create_candidate_incident(
                trigger_obs=persisted_obs
            )

        return PipelineResult(
            observation=persisted_obs,
            is_new=is_new,
            quality_flags=flags,
            anomaly_result=anomaly_res,
            candidate_incident=candidate_incident,
        )

    def process_json(
        self,
        json_str: str,
        source_mode: SourceMode | None = None,
    ) -> PipelineResult:
        """Parse JSON line and process through the pipeline."""
        parse_res = parse_json_line(json_str)
        if not parse_res.is_valid or parse_res.observation is None:
            err_msg = (
                parse_res.error.error if parse_res.error else "Unknown parse error"
            )
            raise ValueError(f"Failed to parse observation: {err_msg}")

        return self.process_raw(
            raw=parse_res.observation,
            raw_payload=json_str,
            source_mode=source_mode,
        )

    def process_source(
        self,
        source: ObservationSource,
    ) -> PipelineSummary:
        """Process an entire ObservationSource stream."""
        summary = PipelineSummary()
        mode = source.source_mode

        if hasattr(source, "observations_with_payload"):
            for raw_obs, raw_payload in source.observations_with_payload():
                result = self.process_raw(
                    raw=raw_obs, raw_payload=raw_payload, source_mode=mode
                )
                summary.record(result)
        else:
            for raw_obs in source.observations():
                result = self.process_raw(raw=raw_obs, source_mode=mode)
                summary.record(result)

        logger.info(
            "Source processing complete: %d received, %d new, %d duplicates, %d anomalies, %d incidents",
            summary.total_received,
            summary.new_observations,
            summary.duplicates,
            summary.anomalies_detected,
            summary.incidents_created,
        )
        return summary

    def process_file(
        self,
        file_path: Path,
        source_mode: SourceMode = SourceMode.CANSAT,
    ) -> PipelineSummary:
        """Process a JSONL recorded telemetry file."""
        summary = PipelineSummary()

        for parse_res in parse_jsonl_file(file_path):
            if parse_res.is_valid and parse_res.observation is not None:
                result = self.process_raw(
                    raw=parse_res.observation,
                    raw_payload=parse_res.raw_json,
                    source_mode=source_mode,
                )
                summary.record(result)
            else:
                logger.warning("Skipping invalid line: %s", parse_res.error)

        return summary
