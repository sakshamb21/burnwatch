"""Unit tests for data quality checks and provenance preservation."""

from __future__ import annotations

from burnwatch.models.observation import (
    NormalizedObservation,
    QualityFlag,
    RawObservation,
    SourceMode,
)
from burnwatch.quality.checks import QualityChecker


def _make_norm_obs(
    device_id: str = "dev-01",
    sequence: int = 1,
    device_time_ms: int = 1000,
    mq135_raw: int = 300,
    temp: float | None = 25.0,
    humidity: float | None = 50.0,
    pressure: float | None = 1013.25,
    lat: float | None = 28.6139,
    lon: float | None = 77.2090,
    gps_fix: bool = True,
    satellites: int = 8,
    source_mode: SourceMode = SourceMode.SIMULATED,
) -> NormalizedObservation:
    """Helper to create a normalized observation with defaults."""
    raw = RawObservation(
        device_id=device_id,
        sequence=sequence,
        device_time_ms=device_time_ms,
        mq135_raw=mq135_raw,
        temperature_c=temp,
        humidity_pct=humidity,
        pressure_hpa=pressure,
        latitude=lat,
        longitude=lon,
        gps_fix=gps_fix,
        satellites=satellites,
    )
    return NormalizedObservation.from_raw(raw, source_mode=source_mode)


class TestQualityCheckerWarmup:
    """Tests for warmup sample detection."""

    def test_initial_samples_flagged_warmup(self) -> None:
        checker = QualityChecker(warmup_count=3)
        for seq in range(1, 4):
            obs = _make_norm_obs(sequence=seq, device_time_ms=seq * 1000)
            flags = checker.check(obs)
            assert QualityFlag.WARMUP in flags
            assert QualityFlag.WARMUP in obs.quality_flags

        # 4th sample should not have warmup
        obs4 = _make_norm_obs(sequence=4, device_time_ms=4000)
        flags4 = checker.check(obs4)
        assert QualityFlag.WARMUP not in flags4

    def test_warmup_tracked_per_device(self) -> None:
        checker = QualityChecker(warmup_count=2)
        # dev-01 consumes warmup
        checker.check(
            _make_norm_obs(device_id="dev-01", sequence=1, device_time_ms=1000)
        )
        checker.check(
            _make_norm_obs(device_id="dev-01", sequence=2, device_time_ms=2000)
        )
        obs1_3 = _make_norm_obs(device_id="dev-01", sequence=3, device_time_ms=3000)
        assert QualityFlag.WARMUP not in checker.check(obs1_3)

        # dev-02 still in warmup
        obs2_1 = _make_norm_obs(device_id="dev-02", sequence=1, device_time_ms=1000)
        assert QualityFlag.WARMUP in checker.check(obs2_1)


class TestQualityCheckerGPS:
    """Tests for GPS quality gating."""

    def test_gps_no_fix_flagged(self) -> None:
        checker = QualityChecker(warmup_count=0)
        obs = _make_norm_obs(gps_fix=False, satellites=0, lat=0.0, lon=0.0)
        flags = checker.check(obs)
        assert QualityFlag.GPS_NO_FIX in flags

    def test_gps_fix_zero_coords_flagged(self) -> None:
        checker = QualityChecker(warmup_count=0)
        obs = _make_norm_obs(gps_fix=True, satellites=6, lat=0.0, lon=0.0)
        flags = checker.check(obs)
        assert QualityFlag.GPS_INVALID_COORDS in flags

    def test_gps_low_satellites(self) -> None:
        checker = QualityChecker(warmup_count=0, min_satellites=4)
        obs = _make_norm_obs(gps_fix=True, satellites=3)
        flags = checker.check(obs)
        assert QualityFlag.LOW_SATELLITES in flags

    def test_valid_gps_no_gps_flags(self) -> None:
        checker = QualityChecker(warmup_count=0)
        obs = _make_norm_obs(gps_fix=True, satellites=8, lat=28.6, lon=77.2)
        flags = checker.check(obs)
        assert QualityFlag.GPS_NO_FIX not in flags
        assert QualityFlag.GPS_INVALID_COORDS not in flags
        assert QualityFlag.LOW_SATELLITES not in flags


class TestQualityCheckerStaleness:
    """Tests for data staleness detection."""

    def test_backwards_device_time_flagged_stale(self) -> None:
        checker = QualityChecker(warmup_count=0)
        obs1 = _make_norm_obs(sequence=1, device_time_ms=50000)
        checker.check(obs1)

        obs2 = _make_norm_obs(sequence=2, device_time_ms=20000)
        flags2 = checker.check(obs2)
        assert QualityFlag.STALE in flags2

    def test_excessive_time_gap_flagged_stale(self) -> None:
        checker = QualityChecker(warmup_count=0, stale_threshold_ms=30000)
        obs1 = _make_norm_obs(sequence=1, device_time_ms=1000)
        checker.check(obs1)

        obs2 = _make_norm_obs(sequence=2, device_time_ms=35000)
        flags2 = checker.check(obs2)
        assert QualityFlag.STALE in flags2

    def test_normal_time_progression_not_stale(self) -> None:
        checker = QualityChecker(warmup_count=0, stale_threshold_ms=30000)
        obs1 = _make_norm_obs(sequence=1, device_time_ms=1000)
        checker.check(obs1)

        obs2 = _make_norm_obs(sequence=2, device_time_ms=2000)
        flags2 = checker.check(obs2)
        assert QualityFlag.STALE not in flags2


class TestQualityCheckerDuplicatesAndGaps:
    """Tests for duplicate packet and sequence gap flags."""

    def test_duplicate_sequence_flagged(self) -> None:
        checker = QualityChecker(warmup_count=0)
        obs1 = _make_norm_obs(sequence=10, device_time_ms=1000)
        checker.check(obs1)

        obs2 = _make_norm_obs(sequence=10, device_time_ms=1000)
        flags2 = checker.check(obs2)
        assert QualityFlag.DUPLICATE in flags2

    def test_sequence_gap_flagged(self) -> None:
        checker = QualityChecker(warmup_count=0)
        obs1 = _make_norm_obs(sequence=1, device_time_ms=1000)
        checker.check(obs1)

        obs2 = _make_norm_obs(sequence=5, device_time_ms=5000)
        flags2 = checker.check(obs2)
        assert QualityFlag.SEQUENCE_GAP in flags2

    def test_consecutive_sequences_no_gap_flag(self) -> None:
        checker = QualityChecker(warmup_count=0)
        obs1 = _make_norm_obs(sequence=1, device_time_ms=1000)
        checker.check(obs1)

        obs2 = _make_norm_obs(sequence=2, device_time_ms=2000)
        flags2 = checker.check(obs2)
        assert QualityFlag.SEQUENCE_GAP not in flags2
        assert QualityFlag.DUPLICATE not in flags2


class TestQualityCheckerEnvironmental:
    """Tests for missing environmental measurements."""

    def test_missing_temp_flagged(self) -> None:
        checker = QualityChecker(warmup_count=0)
        obs = _make_norm_obs(temp=None)
        flags = checker.check(obs)
        assert QualityFlag.MISSING_ENVIRONMENTAL in flags

    def test_missing_humidity_flagged(self) -> None:
        checker = QualityChecker(warmup_count=0)
        obs = _make_norm_obs(humidity=None)
        flags = checker.check(obs)
        assert QualityFlag.MISSING_ENVIRONMENTAL in flags

    def test_missing_pressure_flagged(self) -> None:
        checker = QualityChecker(warmup_count=0)
        obs = _make_norm_obs(pressure=None)
        flags = checker.check(obs)
        assert QualityFlag.MISSING_ENVIRONMENTAL in flags

    def test_all_environmental_present_no_flag(self) -> None:
        checker = QualityChecker(warmup_count=0)
        obs = _make_norm_obs(temp=20.0, humidity=45.0, pressure=1010.0)
        flags = checker.check(obs)
        assert QualityFlag.MISSING_ENVIRONMENTAL not in flags


class TestQualityCheckerResetAndProvenance:
    """Tests for checker reset and provenance preservation."""

    def test_reset_clears_state(self) -> None:
        checker = QualityChecker(warmup_count=2)
        checker.check(_make_norm_obs(sequence=1, device_time_ms=1000))
        checker.check(_make_norm_obs(sequence=2, device_time_ms=2000))
        checker.reset()

        # After reset, next observation is warmup again
        obs = _make_norm_obs(sequence=1, device_time_ms=1000)
        flags = checker.check(obs)
        assert QualityFlag.WARMUP in flags

    def test_provenance_preserved_through_checks(self) -> None:
        checker = QualityChecker(warmup_count=0)
        obs_sim = _make_norm_obs(source_mode=SourceMode.SIMULATED)
        checker.check(obs_sim)
        assert obs_sim.source_mode == SourceMode.SIMULATED
        assert obs_sim.is_simulated is True

        obs_can = _make_norm_obs(source_mode=SourceMode.CANSAT)
        checker.check(obs_can)
        assert obs_can.source_mode == SourceMode.CANSAT
        assert obs_can.is_simulated is False
