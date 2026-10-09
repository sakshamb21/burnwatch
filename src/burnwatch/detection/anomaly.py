"""Anomaly detector using MAD-based deviation from rolling baseline.

Detects relative spikes in MQ135 sensor readings compared to a rolling median baseline.
Maintains persistence counters to distinguish isolated spikes from sustained burning events,
and prevents false alarms during warmup.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from burnwatch.detection.baseline import RollingBaseline
from burnwatch.models.observation import NormalizedObservation, QualityFlag

logger = logging.getLogger(__name__)


@dataclass
class AnomalyDetectionResult:
    """Outcome of anomaly evaluation for an observation."""

    observation_id: str
    device_id: str
    sequence: int
    anomaly_detected: bool
    anomaly_score: float | None
    is_candidate_incident: bool
    consecutive_anomalies: int
    baseline_median: float | None
    baseline_mad: float | None


class AnomalyDetector:
    """Stateful anomaly detector across device telemetry streams.

    Evaluates observations against a per-device rolling baseline using Median
    Absolute Deviation (MAD). Requires sustained anomalous readings (persistence)
    before recommending candidate incident creation.

    Args:
        threshold: MAD multiplier above baseline to flag as anomaly (default 3.0).
        min_samples: Minimum normal samples before anomaly detection begins (default 30).
        warmup_samples: Number of initial samples excluded from baseline/detection (default 10).
        persistence_threshold: Consecutive anomalous samples required to trigger candidate incident (default 3).
        cooldown_samples: Readings to wait after incident trigger before another trigger (default 5).
        min_mad_floor: Minimum MAD floor to handle zero-variance baseline (default 1.0).
        window_size: Rolling baseline window size (default 60).
    """

    def __init__(
        self,
        threshold: float = 3.0,
        min_samples: int = 30,
        warmup_samples: int = 10,
        persistence_threshold: int = 3,
        cooldown_samples: int = 5,
        min_mad_floor: float = 1.0,
        window_size: int = 60,
    ) -> None:
        self.threshold = threshold
        self.min_samples = min_samples
        self.warmup_samples = warmup_samples
        self.persistence_threshold = persistence_threshold
        self.cooldown_samples = cooldown_samples
        self.min_mad_floor = min_mad_floor
        self.window_size = window_size

        self._baselines: dict[str, RollingBaseline] = {}
        self._sample_counts: dict[str, int] = {}
        self._consecutive_anomalies: dict[str, int] = {}
        self._cooldown_remaining: dict[str, int] = {}

    def _get_baseline(self, device_id: str) -> RollingBaseline:
        if device_id not in self._baselines:
            self._baselines[device_id] = RollingBaseline(
                window_size=self.window_size,
                min_mad_floor=self.min_mad_floor,
            )
        return self._baselines[device_id]

    def process(self, obs: NormalizedObservation) -> AnomalyDetectionResult:
        """Evaluate an observation for relative gas-sensor anomalies.

        Updates the observation in-place with anomaly_score and anomaly_detected,
        and returns a detailed AnomalyDetectionResult.

        Args:
            obs: Normalized observation to process.

        Returns:
            AnomalyDetectionResult with detection and candidate incident flags.
        """
        device = obs.device_id
        baseline = self._get_baseline(device)

        # Track sample count
        count = self._sample_counts.get(device, 0) + 1
        self._sample_counts[device] = count

        # Check cooldown decrement
        cooldown = self._cooldown_remaining.get(device, 0)
        if cooldown > 0:
            self._cooldown_remaining[device] = cooldown - 1

        # Check warmup exclusion
        is_warmup = (
            QualityFlag.WARMUP in obs.quality_flags or count <= self.warmup_samples
        )
        if is_warmup:
            obs.anomaly_detected = False
            obs.anomaly_score = None
            return AnomalyDetectionResult(
                observation_id=obs.observation_id,
                device_id=device,
                sequence=obs.sequence,
                anomaly_detected=False,
                anomaly_score=None,
                is_candidate_incident=False,
                consecutive_anomalies=0,
                baseline_median=None,
                baseline_mad=None,
            )

        # Check baseline readiness
        if not baseline.is_ready(self.min_samples):
            baseline.add(obs.mq135_raw)
            obs.anomaly_detected = False
            obs.anomaly_score = None
            return AnomalyDetectionResult(
                observation_id=obs.observation_id,
                device_id=device,
                sequence=obs.sequence,
                anomaly_detected=False,
                anomaly_score=None,
                is_candidate_incident=False,
                consecutive_anomalies=0,
                baseline_median=baseline.get_median(),
                baseline_mad=baseline.get_effective_mad(),
            )

        # Compute anomaly score against current baseline
        score = baseline.calculate_score(obs.mq135_raw, min_samples=self.min_samples)
        median_val = baseline.get_median()
        mad_val = baseline.get_effective_mad()

        consecutive = self._consecutive_anomalies.get(device, 0)
        is_candidate = False

        if score is not None and score >= self.threshold:
            consecutive += 1
            self._consecutive_anomalies[device] = consecutive
            obs.anomaly_detected = True
            obs.anomaly_score = round(score, 2)

            # Check candidate incident trigger
            if consecutive >= self.persistence_threshold:
                if self._cooldown_remaining.get(device, 0) == 0:
                    is_candidate = True
                    self._cooldown_remaining[device] = self.cooldown_samples
                    logger.info(
                        "Candidate incident flagged for %s at seq=%d (score=%.2f, consecutive=%d)",
                        device,
                        obs.sequence,
                        score,
                        consecutive,
                    )
            # Note: Anomalous readings are not added to baseline to prevent baseline drift
        else:
            consecutive = 0
            self._consecutive_anomalies[device] = 0
            obs.anomaly_detected = False
            obs.anomaly_score = round(score, 2) if score is not None else 0.0
            # Normal reading contributes to baseline update
            baseline.add(obs.mq135_raw)

        return AnomalyDetectionResult(
            observation_id=obs.observation_id,
            device_id=device,
            sequence=obs.sequence,
            anomaly_detected=obs.anomaly_detected,
            anomaly_score=obs.anomaly_score,
            is_candidate_incident=is_candidate,
            consecutive_anomalies=consecutive,
            baseline_median=median_val,
            baseline_mad=mad_val,
        )

    def reset(self, device_id: str | None = None) -> None:
        """Reset state for a specific device or all devices."""
        if device_id is None:
            self._baselines.clear()
            self._sample_counts.clear()
            self._consecutive_anomalies.clear()
            self._cooldown_remaining.clear()
        else:
            self._baselines.pop(device_id, None)
            self._sample_counts.pop(device_id, None)
            self._consecutive_anomalies.pop(device_id, None)
            self._cooldown_remaining.pop(device_id, None)
