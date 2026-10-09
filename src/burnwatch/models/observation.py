"""Canonical observation model for BurnWatch.

Defines the validated schema for all observations, whether from the CanSat
hardware or the deterministic simulator. The model enforces sensor ranges,
coordinate validity, and provenance tracking.

Schema version: 1
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import Enum

from pydantic import BaseModel, Field, field_validator, model_validator


class SourceMode(str, Enum):
    """Origin of an observation."""

    SIMULATED = "simulated"
    CANSAT = "cansat"


class QualityFlag(str, Enum):
    """Quality flags assigned during ingestion and processing."""

    GPS_NO_FIX = "gps_no_fix"
    GPS_INVALID_COORDS = "gps_invalid_coords"
    LOW_SATELLITES = "low_satellites"
    WARMUP = "warmup"
    STALE = "stale"
    SEQUENCE_GAP = "sequence_gap"
    DUPLICATE = "duplicate"
    MISSING_ENVIRONMENTAL = "missing_environmental"
    SENSOR_OUT_OF_RANGE = "sensor_out_of_range"


class RawObservation(BaseModel):
    """Raw observation as received from CanSat or simulator.

    This matches the canonical CanSat telemetry format. All fields use the
    exact names and types defined in the project specification.
    """

    device_id: str = Field(..., min_length=1, description="Device identifier")
    sequence: int = Field(..., ge=0, description="Packet sequence number")
    device_time_ms: int = Field(
        ..., ge=0, description="Device-relative timestamp in milliseconds"
    )
    mq135_raw: int = Field(
        ..., ge=0, le=1023, description="MQ135 ADC reading (10-bit: 0-1023)"
    )
    temperature_c: float | None = Field(
        default=None, description="BME280 temperature in °C"
    )
    humidity_pct: float | None = Field(
        default=None, description="BME280 relative humidity %"
    )
    pressure_hpa: float | None = Field(
        default=None, description="BME280 pressure in hPa"
    )
    latitude: float | None = Field(default=None, description="GPS latitude")
    longitude: float | None = Field(default=None, description="GPS longitude")
    gps_fix: bool = Field(default=False, description="Whether GPS has a fix")
    satellites: int = Field(default=0, ge=0, description="Number of GPS satellites")

    @field_validator("temperature_c")
    @classmethod
    def validate_temperature(cls, v: float | None) -> float | None:
        if v is not None and (v < -40.0 or v > 85.0):
            raise ValueError(f"temperature_c must be between -40 and 85, got {v}")
        return v

    @field_validator("humidity_pct")
    @classmethod
    def validate_humidity(cls, v: float | None) -> float | None:
        if v is not None and (v < 0.0 or v > 100.0):
            raise ValueError(f"humidity_pct must be between 0 and 100, got {v}")
        return v

    @field_validator("pressure_hpa")
    @classmethod
    def validate_pressure(cls, v: float | None) -> float | None:
        if v is not None and (v < 300.0 or v > 1100.0):
            raise ValueError(f"pressure_hpa must be between 300 and 1100, got {v}")
        return v

    @field_validator("latitude")
    @classmethod
    def validate_latitude(cls, v: float | None) -> float | None:
        if v is not None and (v < -90.0 or v > 90.0):
            raise ValueError(f"latitude must be between -90 and 90, got {v}")
        return v

    @field_validator("longitude")
    @classmethod
    def validate_longitude(cls, v: float | None) -> float | None:
        if v is not None and (v < -180.0 or v > 180.0):
            raise ValueError(f"longitude must be between -180 and 180, got {v}")
        return v

    model_config = {"extra": "forbid"}


class NormalizedObservation(BaseModel):
    """Normalized observation with backend metadata.

    This is the internal representation used throughout the pipeline.
    It wraps the raw observation with provenance, quality, and processing
    metadata added by the backend.
    """

    # Identity
    observation_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Unique observation identifier assigned by backend",
    )
    schema_version: int = Field(default=1, description="Schema version number")

    # Source provenance
    source_mode: SourceMode = Field(
        ..., description="Whether this observation is simulated or from CanSat"
    )
    is_simulated: bool = Field(
        default=False,
        description="Explicit flag: True if data is synthetic",
    )

    # Timestamps
    received_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="UTC wall-clock time when backend received this observation",
    )

    # Original CanSat fields
    device_id: str
    sequence: int = Field(ge=0)
    device_time_ms: int = Field(ge=0)
    mq135_raw: int = Field(ge=0, le=1023)
    temperature_c: float | None = None
    humidity_pct: float | None = None
    pressure_hpa: float | None = None
    latitude: float | None = None
    longitude: float | None = None
    gps_fix: bool = False
    satellites: int = Field(default=0, ge=0)

    # Raw payload preservation
    raw_payload: str | None = Field(
        default=None,
        description="Original JSON string as received, for audit",
    )

    # Quality and processing
    quality_flags: list[QualityFlag] = Field(
        default_factory=list,
        description="Quality flags assigned during processing",
    )

    # Anomaly result (set by detection module)
    anomaly_score: float | None = Field(
        default=None,
        description="Anomaly score from detector (MAD units from baseline)",
    )
    anomaly_detected: bool = Field(
        default=False,
        description="Whether this observation was flagged as anomalous",
    )

    @model_validator(mode="after")
    def set_simulated_flag(self) -> NormalizedObservation:
        """Ensure is_simulated matches source_mode."""
        self.is_simulated = self.source_mode == SourceMode.SIMULATED
        return self

    @classmethod
    def from_raw(
        cls,
        raw: RawObservation,
        source_mode: SourceMode,
        raw_payload: str | None = None,
    ) -> NormalizedObservation:
        """Create a normalized observation from a validated raw observation.

        Args:
            raw: Validated raw observation.
            source_mode: Whether this came from simulator or CanSat.
            raw_payload: Original JSON string for audit preservation.

        Returns:
            NormalizedObservation with backend metadata populated.
        """
        return cls(
            source_mode=source_mode,
            device_id=raw.device_id,
            sequence=raw.sequence,
            device_time_ms=raw.device_time_ms,
            mq135_raw=raw.mq135_raw,
            temperature_c=raw.temperature_c,
            humidity_pct=raw.humidity_pct,
            pressure_hpa=raw.pressure_hpa,
            latitude=raw.latitude,
            longitude=raw.longitude,
            gps_fix=raw.gps_fix,
            satellites=raw.satellites,
            raw_payload=raw_payload,
        )

    model_config = {"extra": "forbid"}
