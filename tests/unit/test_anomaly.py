"""Unit tests for AnomalyDetector."""

from __future__ import annotations

from burnwatch.detection.anomaly import AnomalyDetector
from burnwatch.models.observation import (
    NormalizedObservation,
    QualityFlag,
    RawObservation,
    SourceMode,
)


def _make_obs(
    seq: int,
    mq135: int = 300,
    warmup: bool = False,
    device_id: str = "dev-01",
) -> NormalizedObservation:
    flags = [QualityFlag.WARMUP] if warmup else []
    raw = RawObservation(
        device_id=device_id,
        sequence=seq,
        device_time_ms=seq * 1000,
        mq135_raw=mq135,
        latitude=28.6,
        longitude=77.2,
        gps_fix=True,
        satellites=7,
    )
    obs = NormalizedObservation.from_raw(raw, SourceMode.SIMULATED)
    obs.quality_flags = flags
    return obs


class TestAnomalyDetector:
    """Tests for AnomalyDetector logic, persistence, and cooldown."""

    def test_warmup_samples_excluded(self) -> None:
        detector = AnomalyDetector(warmup_samples=5, min_samples=5)
        for i in range(1, 6):
            obs = _make_obs(seq=i, mq135=900, warmup=True)
            res = detector.process(obs)
            assert not res.anomaly_detected
            assert res.anomaly_score is None
            assert not res.is_candidate_incident

    def test_insufficient_samples_not_detected(self) -> None:
        detector = AnomalyDetector(warmup_samples=2, min_samples=10)
        # Process warmup
        for i in range(1, 3):
            detector.process(_make_obs(seq=i, warmup=True))
        # Process samples 3 through 8 (less than min_samples=10)
        for i in range(3, 9):
            res = detector.process(_make_obs(seq=i, mq135=300))
            assert not res.anomaly_detected
            assert res.anomaly_score is None

    def test_spike_detection(self) -> None:
        detector = AnomalyDetector(
            warmup_samples=0,
            min_samples=10,
            threshold=3.0,
            min_mad_floor=2.0,
            persistence_threshold=3,
        )
        # Establish baseline around 300
        for i in range(1, 15):
            res = detector.process(_make_obs(seq=i, mq135=300))
            assert not res.anomaly_detected

        # Single spike to 500
        res_spike = detector.process(_make_obs(seq=15, mq135=500))
        assert res_spike.anomaly_detected
        assert res_spike.anomaly_score is not None
        assert res_spike.anomaly_score > 3.0
        # Not yet a candidate incident (persistence_threshold=3)
        assert not res_spike.is_candidate_incident
        assert res_spike.consecutive_anomalies == 1

    def test_sustained_anomaly_triggers_candidate_incident(self) -> None:
        detector = AnomalyDetector(
            warmup_samples=0,
            min_samples=10,
            threshold=3.0,
            min_mad_floor=2.0,
            persistence_threshold=3,
        )
        for i in range(1, 15):
            detector.process(_make_obs(seq=i, mq135=300))

        # 3 consecutive spikes
        res1 = detector.process(_make_obs(seq=15, mq135=600))
        assert res1.anomaly_detected
        assert not res1.is_candidate_incident
        assert res1.consecutive_anomalies == 1

        res2 = detector.process(_make_obs(seq=16, mq135=600))
        assert res2.anomaly_detected
        assert not res2.is_candidate_incident
        assert res2.consecutive_anomalies == 2

        res3 = detector.process(_make_obs(seq=17, mq135=600))
        assert res3.anomaly_detected
        # 3rd consecutive meets persistence threshold!
        assert res3.is_candidate_incident
        assert res3.consecutive_anomalies == 3

    def test_cooldown_prevents_immediate_retrigger(self) -> None:
        detector = AnomalyDetector(
            warmup_samples=0,
            min_samples=10,
            threshold=3.0,
            persistence_threshold=2,
            cooldown_samples=3,
        )
        for i in range(1, 15):
            detector.process(_make_obs(seq=i, mq135=300))

        # 2 spikes trigger incident
        detector.process(_make_obs(seq=15, mq135=500))
        res2 = detector.process(_make_obs(seq=16, mq135=500))
        assert res2.is_candidate_incident

        # 3rd continuous spike should be anomaly, but NOT a new candidate incident due to cooldown
        res3 = detector.process(_make_obs(seq=17, mq135=500))
        assert res3.anomaly_detected
        assert not res3.is_candidate_incident

    def test_isolated_spike_resets_consecutive(self) -> None:
        detector = AnomalyDetector(
            warmup_samples=0,
            min_samples=10,
            threshold=3.0,
            persistence_threshold=2,
        )
        for i in range(1, 15):
            detector.process(_make_obs(seq=i, mq135=300))

        # Spike 1
        res1 = detector.process(_make_obs(seq=15, mq135=600))
        assert res1.consecutive_anomalies == 1

        # Return to normal
        res_norm = detector.process(_make_obs(seq=16, mq135=300))
        assert res_norm.consecutive_anomalies == 0
        assert not res_norm.anomaly_detected

        # Spike 2 is now back at consecutive=1, so no candidate
        res2 = detector.process(_make_obs(seq=17, mq135=600))
        assert res2.consecutive_anomalies == 1
        assert not res2.is_candidate_incident

    def test_multiple_devices_independent(self) -> None:
        detector = AnomalyDetector(
            warmup_samples=0, min_samples=5, threshold=3.0, min_mad_floor=1.0
        )
        for i in range(1, 10):
            detector.process(_make_obs(seq=i, mq135=200, device_id="dev-A"))
            detector.process(_make_obs(seq=i, mq135=500, device_id="dev-B"))

        # dev-A gets 400 (spike from 200) -> anomaly
        res_a = detector.process(_make_obs(seq=10, mq135=400, device_id="dev-A"))
        assert res_a.anomaly_detected

        # dev-B gets 502 (within threshold for 500, score=2.0 < 3.0) -> not anomaly
        res_b = detector.process(_make_obs(seq=10, mq135=502, device_id="dev-B"))
        assert not res_b.anomaly_detected
