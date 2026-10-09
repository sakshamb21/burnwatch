"""Data quality checks for BurnWatch observations.

Assigns quality flags to normalized observations based on GPS validity,
sensor warmup, data staleness, and environmental completeness.

Quality checks are applied after parsing and validation, before anomaly
detection. Observations with quality issues are still stored but flagged.
"""

from __future__ import annotations

import logging

from burnwatch.models.observation import NormalizedObservation, QualityFlag

logger = logging.getLogger(__name__)


class QualityChecker:
    """Applies quality flags to normalized observations.

    Maintains state for warmup detection and staleness tracking.

    Args:
        warmup_count: Number of initial observations considered warmup.
        stale_threshold_ms: Device time gap considered stale (in ms).
        min_satellites: Minimum satellites for reliable GPS fix.
    """

    def __init__(
        self,
        warmup_count: int = 10,
        stale_threshold_ms: int = 30000,
        min_satellites: int = 4,
    ) -> None:
        self.warmup_count = warmup_count
        self.stale_threshold_ms = stale_threshold_ms
        self.min_satellites = min_satellites

        # Per-device counters
        self._observation_counts: dict[str, int] = {}
        self._last_device_time: dict[str, int] = {}
        self._seen_sequences: dict[str, set[int]] = {}

    def check(self, obs: NormalizedObservation) -> list[QualityFlag]:
        """Apply quality checks and return flags.

        Flags are also appended to the observation's quality_flags list.

        Args:
            obs: Normalized observation to check.

        Returns:
            List of quality flags assigned to this observation.
        """
        flags: list[QualityFlag] = []
        device = obs.device_id

        # Initialize per-device state
        if device not in self._observation_counts:
            self._observation_counts[device] = 0
            self._seen_sequences[device] = set()

        self._observation_counts[device] += 1
        count = self._observation_counts[device]

        # Warmup check
        if count <= self.warmup_count:
            flags.append(QualityFlag.WARMUP)

        # GPS checks
        if not obs.gps_fix:
            flags.append(QualityFlag.GPS_NO_FIX)
        elif obs.latitude is None or obs.longitude is None:
            flags.append(QualityFlag.GPS_INVALID_COORDS)
        elif obs.latitude == 0.0 and obs.longitude == 0.0:
            flags.append(QualityFlag.GPS_INVALID_COORDS)

        if obs.gps_fix and obs.satellites < self.min_satellites:
            flags.append(QualityFlag.LOW_SATELLITES)

        # Staleness check (device time going backwards or large gap)
        last_time = self._last_device_time.get(device)
        if last_time is not None:
            time_diff = obs.device_time_ms - last_time
            if time_diff < 0:
                flags.append(QualityFlag.STALE)
            elif time_diff > self.stale_threshold_ms:
                flags.append(QualityFlag.STALE)
            if obs.device_time_ms > last_time:
                self._last_device_time[device] = obs.device_time_ms
        else:
            self._last_device_time[device] = obs.device_time_ms

        # Duplicate check
        is_duplicate = False
        seq_set = self._seen_sequences[device]
        if obs.sequence in seq_set:
            flags.append(QualityFlag.DUPLICATE)
            is_duplicate = True
        else:
            seq_set.add(obs.sequence)

        # Sequence gap check (do not check on duplicates)
        if not is_duplicate and len(seq_set) > 1:
            expected_max = max(seq_set)
            expected_min = min(seq_set)
            expected_count = expected_max - expected_min + 1
            if len(seq_set) < expected_count:
                # Only flag if this observation contributes to a gap
                if obs.sequence > 0 and (obs.sequence - 1) not in seq_set:
                    flags.append(QualityFlag.SEQUENCE_GAP)

        # Missing environmental data
        if (
            obs.temperature_c is None
            or obs.humidity_pct is None
            or obs.pressure_hpa is None
        ):
            flags.append(QualityFlag.MISSING_ENVIRONMENTAL)

        # Apply flags to observation
        obs.quality_flags.extend(flags)

        if flags:
            logger.debug(
                "Quality flags for %s seq=%d: %s",
                device,
                obs.sequence,
                [f.value for f in flags],
            )

        return flags

    def reset(self, device_id: str | None = None) -> None:
        """Reset quality checker state.

        Args:
            device_id: Reset only this device, or all if None.
        """
        if device_id is None:
            self._observation_counts.clear()
            self._last_device_time.clear()
            self._seen_sequences.clear()
        else:
            self._observation_counts.pop(device_id, None)
            self._last_device_time.pop(device_id, None)
            self._seen_sequences.pop(device_id, None)
