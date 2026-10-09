"""Deterministic simulator for BurnWatch observations.

Generates synthetic observations with reproducible output using a fixed
random seed. Supports multiple scenarios for testing different pipeline
behaviors.

All generated data is explicitly marked as simulated.
"""

from __future__ import annotations

import random
from collections.abc import Iterator
from enum import Enum
from pathlib import Path

from burnwatch.models.observation import RawObservation, SourceMode
from burnwatch.sources.base import ObservationSource


class Scenario(str, Enum):
    """Simulation scenarios for testing."""

    NORMAL = "normal"
    DRIFT = "drift"
    SPIKE = "spike"
    SUSTAINED_ANOMALY = "sustained_anomaly"
    INVALID_GPS = "invalid_gps"
    PACKET_GAP = "packet_gap"
    DUPLICATE_PACKET = "duplicate_packet"
    STALE_DATA = "stale_data"
    MISSING_FIELDS = "missing_fields"
    WARMUP = "warmup"


# Alias for clarity
SimulatorScenario = Scenario


# Default simulation parameters
_DEFAULT_DEVICE_ID = "burnwatch-sim-01"
_DEFAULT_BASE_LAT = 28.75
_DEFAULT_BASE_LON = 77.12
_DEFAULT_BASE_MQ135 = 350
_DEFAULT_BASE_TEMP = 30.0
_DEFAULT_BASE_HUMIDITY = 50.0
_DEFAULT_BASE_PRESSURE = 1013.25


class SimulatorSource(ObservationSource):
    """Deterministic observation generator.

    Produces synthetic observations matching the canonical CanSat schema.
    Uses a seeded random number generator for full reproducibility.

    Args:
        scenario: Simulation scenario to generate.
        count: Number of observations to produce.
        seed: Random seed for deterministic output.
        interval_ms: Simulated time between observations in milliseconds.
        device_id: Simulated device identifier.
    """

    def __init__(
        self,
        scenario: Scenario = Scenario.NORMAL,
        count: int = 200,
        seed: int = 42,
        interval_ms: int = 2000,
        device_id: str = _DEFAULT_DEVICE_ID,
    ) -> None:
        self.scenario = scenario
        self.count = count
        self.seed = seed
        self.interval_ms = interval_ms
        self.device_id = device_id

    @property
    def source_mode(self) -> SourceMode:
        return SourceMode.SIMULATED

    def observations(self) -> Iterator[RawObservation]:
        """Generate observations for the configured scenario."""
        rng = random.Random(self.seed)
        generator = _SCENARIO_GENERATORS[self.scenario]
        yield from generator(self, rng)

    def to_jsonl(self, output_path: Path) -> int:
        """Write observations to a JSONL file.

        Args:
            output_path: Path to write the JSONL file.

        Returns:
            Number of records written.
        """
        output_path.parent.mkdir(parents=True, exist_ok=True)
        count = 0
        with open(output_path, "w", encoding="utf-8") as f:
            for obs in self.observations():
                f.write(obs.model_dump_json() + "\n")
                count += 1
        return count


def _base_observation(
    sim: SimulatorSource,
    rng: random.Random,
    seq: int,
    time_ms: int,
    mq135: int | None = None,
    temp: float | None = None,
    humidity: float | None = None,
    pressure: float | None = None,
    lat: float | None = None,
    lon: float | None = None,
    gps_fix: bool = True,
    satellites: int | None = None,
) -> RawObservation:
    """Create a plausible base observation with optional overrides."""
    return RawObservation(
        device_id=sim.device_id,
        sequence=seq,
        device_time_ms=time_ms,
        mq135_raw=mq135
        if mq135 is not None
        else _DEFAULT_BASE_MQ135 + rng.randint(-20, 20),
        temperature_c=temp
        if temp is not None
        else _DEFAULT_BASE_TEMP + rng.uniform(-2, 2),
        humidity_pct=humidity
        if humidity is not None
        else _DEFAULT_BASE_HUMIDITY + rng.uniform(-5, 5),
        pressure_hpa=pressure
        if pressure is not None
        else _DEFAULT_BASE_PRESSURE + rng.uniform(-2, 2),
        latitude=lat
        if lat is not None
        else _DEFAULT_BASE_LAT + rng.uniform(-0.005, 0.005),
        longitude=lon
        if lon is not None
        else _DEFAULT_BASE_LON + rng.uniform(-0.005, 0.005),
        gps_fix=gps_fix,
        satellites=satellites if satellites is not None else rng.randint(4, 12),
    )


def _generate_normal(
    sim: SimulatorSource, rng: random.Random
) -> Iterator[RawObservation]:
    """Normal operation: stable readings with minor noise."""
    for i in range(sim.count):
        yield _base_observation(sim, rng, seq=i, time_ms=i * sim.interval_ms)


def _generate_drift(
    sim: SimulatorSource, rng: random.Random
) -> Iterator[RawObservation]:
    """Gradual MQ135 baseline drift upward."""
    for i in range(sim.count):
        drift = int(i * 0.5)  # Slow upward drift
        base_mq = _DEFAULT_BASE_MQ135 + drift + rng.randint(-10, 10)
        base_mq = min(base_mq, 1023)  # Clamp to ADC range
        yield _base_observation(
            sim, rng, seq=i, time_ms=i * sim.interval_ms, mq135=base_mq
        )


def _generate_spike(
    sim: SimulatorSource, rng: random.Random
) -> Iterator[RawObservation]:
    """Normal readings with sharp MQ135 spikes at known positions."""
    spike_positions = {sim.count // 4, sim.count // 2, 3 * sim.count // 4}
    for i in range(sim.count):
        if i in spike_positions:
            mq135 = min(_DEFAULT_BASE_MQ135 + rng.randint(250, 400), 1023)
        else:
            mq135 = _DEFAULT_BASE_MQ135 + rng.randint(-20, 20)
        yield _base_observation(
            sim, rng, seq=i, time_ms=i * sim.interval_ms, mq135=mq135
        )


def _generate_sustained_anomaly(
    sim: SimulatorSource, rng: random.Random
) -> Iterator[RawObservation]:
    """Elevated MQ135 for a sustained period."""
    anomaly_start = sim.count // 3
    anomaly_end = 2 * sim.count // 3
    for i in range(sim.count):
        if anomaly_start <= i < anomaly_end:
            mq135 = min(_DEFAULT_BASE_MQ135 + rng.randint(150, 250), 1023)
        else:
            mq135 = _DEFAULT_BASE_MQ135 + rng.randint(-20, 20)
        yield _base_observation(
            sim, rng, seq=i, time_ms=i * sim.interval_ms, mq135=mq135
        )


def _generate_invalid_gps(
    sim: SimulatorSource, rng: random.Random
) -> Iterator[RawObservation]:
    """Observations with intermittent GPS failures."""
    for i in range(sim.count):
        if i % 5 == 0:  # Every 5th observation has bad GPS
            yield _base_observation(
                sim,
                rng,
                seq=i,
                time_ms=i * sim.interval_ms,
                gps_fix=False,
                satellites=0,
                lat=0.0,
                lon=0.0,
            )
        else:
            yield _base_observation(sim, rng, seq=i, time_ms=i * sim.interval_ms)


def _generate_packet_gap(
    sim: SimulatorSource, rng: random.Random
) -> Iterator[RawObservation]:
    """Observations with sequence gaps (missing packets)."""
    gap_positions = {sim.count // 4, sim.count // 4 + 1, sim.count // 2}
    seq = 0
    for i in range(sim.count):
        if i in gap_positions:
            seq += rng.randint(2, 5)  # Skip some sequence numbers
        yield _base_observation(sim, rng, seq=seq, time_ms=seq * sim.interval_ms)
        seq += 1


def _generate_duplicate_packet(
    sim: SimulatorSource, rng: random.Random
) -> Iterator[RawObservation]:
    """Normal observations with intentional duplicates."""
    dup_positions = {sim.count // 4, sim.count // 2}
    for i in range(sim.count):
        obs = _base_observation(sim, rng, seq=i, time_ms=i * sim.interval_ms)
        yield obs
        if i in dup_positions:
            # Yield the same observation again (same seq and time)
            yield RawObservation(
                device_id=obs.device_id,
                sequence=obs.sequence,
                device_time_ms=obs.device_time_ms,
                mq135_raw=obs.mq135_raw,
                temperature_c=obs.temperature_c,
                humidity_pct=obs.humidity_pct,
                pressure_hpa=obs.pressure_hpa,
                latitude=obs.latitude,
                longitude=obs.longitude,
                gps_fix=obs.gps_fix,
                satellites=obs.satellites,
            )


def _generate_stale_data(
    sim: SimulatorSource, rng: random.Random
) -> Iterator[RawObservation]:
    """Observations with some having very old device_time_ms (stale)."""
    for i in range(sim.count):
        if i % 10 == 0 and i > 0:
            # Stale: device_time_ms doesn't advance
            stale_time = max(0, (i - 20) * sim.interval_ms)
            yield _base_observation(sim, rng, seq=i, time_ms=stale_time)
        else:
            yield _base_observation(sim, rng, seq=i, time_ms=i * sim.interval_ms)


def _generate_missing_fields(
    sim: SimulatorSource, rng: random.Random
) -> Iterator[RawObservation]:
    """Observations with some optional environmental fields missing."""
    for i in range(sim.count):
        base = _base_observation(sim, rng, seq=i, time_ms=i * sim.interval_ms)
        if i % 4 == 0:
            # Missing temperature
            yield RawObservation(
                device_id=base.device_id,
                sequence=base.sequence,
                device_time_ms=base.device_time_ms,
                mq135_raw=base.mq135_raw,
                temperature_c=None,
                humidity_pct=base.humidity_pct,
                pressure_hpa=base.pressure_hpa,
                latitude=base.latitude,
                longitude=base.longitude,
                gps_fix=base.gps_fix,
                satellites=base.satellites,
            )
        elif i % 4 == 1:
            # Missing humidity
            yield RawObservation(
                device_id=base.device_id,
                sequence=base.sequence,
                device_time_ms=base.device_time_ms,
                mq135_raw=base.mq135_raw,
                temperature_c=base.temperature_c,
                humidity_pct=None,
                pressure_hpa=base.pressure_hpa,
                latitude=base.latitude,
                longitude=base.longitude,
                gps_fix=base.gps_fix,
                satellites=base.satellites,
            )
        elif i % 4 == 2:
            # Missing pressure
            yield RawObservation(
                device_id=base.device_id,
                sequence=base.sequence,
                device_time_ms=base.device_time_ms,
                mq135_raw=base.mq135_raw,
                temperature_c=base.temperature_c,
                humidity_pct=base.humidity_pct,
                pressure_hpa=None,
                latitude=base.latitude,
                longitude=base.longitude,
                gps_fix=base.gps_fix,
                satellites=base.satellites,
            )
        else:
            yield base


def _generate_warmup(
    sim: SimulatorSource, rng: random.Random
) -> Iterator[RawObservation]:
    """First N observations have erratic MQ135 readings (warmup behavior)."""
    warmup_count = min(10, sim.count)
    for i in range(sim.count):
        if i < warmup_count:
            # Warmup: high, unstable readings
            mq135 = min(rng.randint(600, 950), 1023)
        else:
            mq135 = _DEFAULT_BASE_MQ135 + rng.randint(-20, 20)
        yield _base_observation(
            sim, rng, seq=i, time_ms=i * sim.interval_ms, mq135=mq135
        )


# Map scenario enum to generator function
_SCENARIO_GENERATORS = {
    Scenario.NORMAL: _generate_normal,
    Scenario.DRIFT: _generate_drift,
    Scenario.SPIKE: _generate_spike,
    Scenario.SUSTAINED_ANOMALY: _generate_sustained_anomaly,
    Scenario.INVALID_GPS: _generate_invalid_gps,
    Scenario.PACKET_GAP: _generate_packet_gap,
    Scenario.DUPLICATE_PACKET: _generate_duplicate_packet,
    Scenario.STALE_DATA: _generate_stale_data,
    Scenario.MISSING_FIELDS: _generate_missing_fields,
    Scenario.WARMUP: _generate_warmup,
}
