"""Tests for the canonical observation model."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from burnwatch.models.observation import (
    NormalizedObservation,
    QualityFlag,
    RawObservation,
    SourceMode,
)


class TestRawObservation:
    """Tests for RawObservation validation."""

    def test_canonical_sample_validates(self, canonical_obs: dict) -> None:
        """The exact canonical observation from the project spec must validate."""
        obs = RawObservation(**canonical_obs)
        assert obs.device_id == "burnwatch-cansat-01"
        assert obs.sequence == 184
        assert obs.device_time_ms == 368000
        assert obs.mq135_raw == 412
        assert obs.temperature_c == 31.4
        assert obs.humidity_pct == 48.2
        assert obs.pressure_hpa == 1001.3
        assert obs.latitude == 28.75
        assert obs.longitude == 77.12
        assert obs.gps_fix is True
        assert obs.satellites == 7

    def test_missing_optional_environmental_fields(self) -> None:
        """Temperature, humidity, pressure are optional."""
        data = {
            "device_id": "test-01",
            "sequence": 1,
            "device_time_ms": 2000,
            "mq135_raw": 300,
            "gps_fix": False,
            "satellites": 0,
        }
        obs = RawObservation(**data)
        assert obs.temperature_c is None
        assert obs.humidity_pct is None
        assert obs.pressure_hpa is None
        assert obs.latitude is None
        assert obs.longitude is None

    def test_missing_required_device_id(self) -> None:
        """device_id is required."""
        data = {
            "sequence": 1,
            "device_time_ms": 2000,
            "mq135_raw": 300,
        }
        with pytest.raises(ValidationError) as exc_info:
            RawObservation(**data)
        assert "device_id" in str(exc_info.value)

    def test_missing_required_sequence(self, canonical_obs: dict) -> None:
        """sequence is required."""
        del canonical_obs["sequence"]
        with pytest.raises(ValidationError) as exc_info:
            RawObservation(**canonical_obs)
        assert "sequence" in str(exc_info.value)

    def test_missing_required_device_time_ms(self, canonical_obs: dict) -> None:
        """device_time_ms is required."""
        del canonical_obs["device_time_ms"]
        with pytest.raises(ValidationError) as exc_info:
            RawObservation(**canonical_obs)
        assert "device_time_ms" in str(exc_info.value)

    def test_missing_required_mq135_raw(self, canonical_obs: dict) -> None:
        """mq135_raw is required."""
        del canonical_obs["mq135_raw"]
        with pytest.raises(ValidationError) as exc_info:
            RawObservation(**canonical_obs)
        assert "mq135_raw" in str(exc_info.value)

    def test_invalid_latitude_too_high(self, canonical_obs: dict) -> None:
        """Latitude > 90 must be rejected."""
        canonical_obs["latitude"] = 91.0
        with pytest.raises(ValidationError) as exc_info:
            RawObservation(**canonical_obs)
        assert "latitude" in str(exc_info.value)

    def test_invalid_latitude_too_low(self, canonical_obs: dict) -> None:
        """Latitude < -90 must be rejected."""
        canonical_obs["latitude"] = -91.0
        with pytest.raises(ValidationError) as exc_info:
            RawObservation(**canonical_obs)
        assert "latitude" in str(exc_info.value)

    def test_invalid_longitude_too_high(self, canonical_obs: dict) -> None:
        """Longitude > 180 must be rejected."""
        canonical_obs["longitude"] = 181.0
        with pytest.raises(ValidationError) as exc_info:
            RawObservation(**canonical_obs)
        assert "longitude" in str(exc_info.value)

    def test_invalid_longitude_too_low(self, canonical_obs: dict) -> None:
        """Longitude < -180 must be rejected."""
        canonical_obs["longitude"] = -181.0
        with pytest.raises(ValidationError) as exc_info:
            RawObservation(**canonical_obs)
        assert "longitude" in str(exc_info.value)

    def test_invalid_mq135_too_high(self, canonical_obs: dict) -> None:
        """MQ135 > 1023 must be rejected (10-bit ADC)."""
        canonical_obs["mq135_raw"] = 1024
        with pytest.raises(ValidationError) as exc_info:
            RawObservation(**canonical_obs)
        assert "mq135_raw" in str(exc_info.value)

    def test_invalid_mq135_negative(self, canonical_obs: dict) -> None:
        """MQ135 < 0 must be rejected."""
        canonical_obs["mq135_raw"] = -1
        with pytest.raises(ValidationError) as exc_info:
            RawObservation(**canonical_obs)
        assert "mq135_raw" in str(exc_info.value)

    def test_invalid_temperature_too_high(self, canonical_obs: dict) -> None:
        """Temperature > 85°C must be rejected."""
        canonical_obs["temperature_c"] = 86.0
        with pytest.raises(ValidationError) as exc_info:
            RawObservation(**canonical_obs)
        assert "temperature_c" in str(exc_info.value)

    def test_invalid_temperature_too_low(self, canonical_obs: dict) -> None:
        """Temperature < -40°C must be rejected."""
        canonical_obs["temperature_c"] = -41.0
        with pytest.raises(ValidationError) as exc_info:
            RawObservation(**canonical_obs)
        assert "temperature_c" in str(exc_info.value)

    def test_invalid_humidity_too_high(self, canonical_obs: dict) -> None:
        """Humidity > 100% must be rejected."""
        canonical_obs["humidity_pct"] = 101.0
        with pytest.raises(ValidationError) as exc_info:
            RawObservation(**canonical_obs)
        assert "humidity_pct" in str(exc_info.value)

    def test_invalid_humidity_negative(self, canonical_obs: dict) -> None:
        """Humidity < 0% must be rejected."""
        canonical_obs["humidity_pct"] = -1.0
        with pytest.raises(ValidationError) as exc_info:
            RawObservation(**canonical_obs)
        assert "humidity_pct" in str(exc_info.value)

    def test_invalid_pressure_too_high(self, canonical_obs: dict) -> None:
        """Pressure > 1100 hPa must be rejected."""
        canonical_obs["pressure_hpa"] = 1101.0
        with pytest.raises(ValidationError) as exc_info:
            RawObservation(**canonical_obs)
        assert "pressure_hpa" in str(exc_info.value)

    def test_invalid_pressure_too_low(self, canonical_obs: dict) -> None:
        """Pressure < 300 hPa must be rejected."""
        canonical_obs["pressure_hpa"] = 299.0
        with pytest.raises(ValidationError) as exc_info:
            RawObservation(**canonical_obs)
        assert "pressure_hpa" in str(exc_info.value)

    def test_negative_sequence_rejected(self, canonical_obs: dict) -> None:
        """Sequence number must be >= 0."""
        canonical_obs["sequence"] = -1
        with pytest.raises(ValidationError):
            RawObservation(**canonical_obs)

    def test_negative_device_time_rejected(self, canonical_obs: dict) -> None:
        """Device time must be >= 0."""
        canonical_obs["device_time_ms"] = -1
        with pytest.raises(ValidationError):
            RawObservation(**canonical_obs)

    def test_unknown_fields_rejected(self, canonical_obs: dict) -> None:
        """Unknown fields must be rejected (extra='forbid')."""
        canonical_obs["unknown_field"] = "surprise"
        with pytest.raises(ValidationError) as exc_info:
            RawObservation(**canonical_obs)
        assert "unknown_field" in str(exc_info.value) or "extra" in str(exc_info.value)

    def test_empty_device_id_rejected(self, canonical_obs: dict) -> None:
        """Empty device_id must be rejected."""
        canonical_obs["device_id"] = ""
        with pytest.raises(ValidationError):
            RawObservation(**canonical_obs)

    def test_boundary_mq135_zero(self, canonical_obs: dict) -> None:
        """MQ135 = 0 is valid."""
        canonical_obs["mq135_raw"] = 0
        obs = RawObservation(**canonical_obs)
        assert obs.mq135_raw == 0

    def test_boundary_mq135_max(self, canonical_obs: dict) -> None:
        """MQ135 = 1023 is valid."""
        canonical_obs["mq135_raw"] = 1023
        obs = RawObservation(**canonical_obs)
        assert obs.mq135_raw == 1023

    def test_boundary_coords(self, canonical_obs: dict) -> None:
        """Extreme valid coordinates."""
        canonical_obs["latitude"] = -90.0
        canonical_obs["longitude"] = 180.0
        obs = RawObservation(**canonical_obs)
        assert obs.latitude == -90.0
        assert obs.longitude == 180.0

    def test_from_json_string(self, canonical_obs_json: str) -> None:
        """Can parse from JSON string."""
        data = json.loads(canonical_obs_json)
        obs = RawObservation(**data)
        assert obs.device_id == "burnwatch-cansat-01"

    def test_gps_fix_defaults_false(self) -> None:
        """gps_fix defaults to False when not provided."""
        data = {
            "device_id": "test-01",
            "sequence": 0,
            "device_time_ms": 0,
            "mq135_raw": 100,
        }
        obs = RawObservation(**data)
        assert obs.gps_fix is False
        assert obs.satellites == 0


class TestNormalizedObservation:
    """Tests for NormalizedObservation with backend metadata."""

    def test_from_raw_simulated(self, canonical_obs: dict) -> None:
        """Create normalized observation from raw with simulated source."""
        raw = RawObservation(**canonical_obs)
        payload = json.dumps(canonical_obs)
        norm = NormalizedObservation.from_raw(
            raw, SourceMode.SIMULATED, raw_payload=payload
        )

        assert norm.source_mode == SourceMode.SIMULATED
        assert norm.is_simulated is True
        assert norm.device_id == "burnwatch-cansat-01"
        assert norm.mq135_raw == 412
        assert norm.raw_payload == payload
        assert norm.observation_id  # UUID assigned
        assert norm.schema_version == 1
        assert norm.received_at is not None
        assert norm.quality_flags == []
        assert norm.anomaly_detected is False

    def test_from_raw_cansat(self, canonical_obs: dict) -> None:
        """Create normalized observation from raw with CanSat source."""
        raw = RawObservation(**canonical_obs)
        norm = NormalizedObservation.from_raw(raw, SourceMode.CANSAT)

        assert norm.source_mode == SourceMode.CANSAT
        assert norm.is_simulated is False

    def test_simulated_flag_auto_set(self, canonical_obs: dict) -> None:
        """is_simulated is automatically set based on source_mode."""
        raw = RawObservation(**canonical_obs)
        norm = NormalizedObservation.from_raw(raw, SourceMode.SIMULATED)
        assert norm.is_simulated is True

        norm2 = NormalizedObservation.from_raw(raw, SourceMode.CANSAT)
        assert norm2.is_simulated is False

    def test_observation_id_unique(self, canonical_obs: dict) -> None:
        """Each normalized observation gets a unique ID."""
        raw = RawObservation(**canonical_obs)
        norm1 = NormalizedObservation.from_raw(raw, SourceMode.SIMULATED)
        norm2 = NormalizedObservation.from_raw(raw, SourceMode.SIMULATED)
        assert norm1.observation_id != norm2.observation_id

    def test_received_at_is_utc(self, canonical_obs: dict) -> None:
        """received_at must be UTC."""
        raw = RawObservation(**canonical_obs)
        norm = NormalizedObservation.from_raw(raw, SourceMode.SIMULATED)
        assert norm.received_at.tzinfo is not None
        assert str(norm.received_at.tzinfo) == "UTC"

    def test_quality_flags_appendable(self, canonical_obs: dict) -> None:
        """Quality flags can be added after creation."""
        raw = RawObservation(**canonical_obs)
        norm = NormalizedObservation.from_raw(raw, SourceMode.CANSAT)
        norm.quality_flags.append(QualityFlag.GPS_NO_FIX)
        assert QualityFlag.GPS_NO_FIX in norm.quality_flags

    def test_anomaly_fields_settable(self, canonical_obs: dict) -> None:
        """Anomaly results can be set after creation."""
        raw = RawObservation(**canonical_obs)
        norm = NormalizedObservation.from_raw(raw, SourceMode.CANSAT)
        norm.anomaly_score = 4.5
        norm.anomaly_detected = True
        assert norm.anomaly_score == 4.5
        assert norm.anomaly_detected is True

    def test_schema_version(self, canonical_obs: dict) -> None:
        """Schema version defaults to 1."""
        raw = RawObservation(**canonical_obs)
        norm = NormalizedObservation.from_raw(raw, SourceMode.SIMULATED)
        assert norm.schema_version == 1

    def test_raw_payload_preserved(self, canonical_obs: dict) -> None:
        """Original payload is preserved for audit."""
        raw = RawObservation(**canonical_obs)
        payload = json.dumps(canonical_obs)
        norm = NormalizedObservation.from_raw(
            raw, SourceMode.CANSAT, raw_payload=payload
        )
        assert norm.raw_payload == payload
        # Verify it can be deserialized back
        recovered = json.loads(norm.raw_payload)
        assert recovered["device_id"] == "burnwatch-cansat-01"
