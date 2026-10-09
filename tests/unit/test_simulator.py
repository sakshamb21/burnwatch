"""Tests for the deterministic simulator."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from burnwatch.models.observation import RawObservation, SourceMode
from burnwatch.sources.simulator import Scenario, SimulatorSource


class TestSimulatorDeterminism:
    """Verify that the simulator produces reproducible output."""

    def test_same_seed_same_output(self) -> None:
        """Same seed must produce identical observations."""
        sim1 = SimulatorSource(scenario=Scenario.NORMAL, count=50, seed=42)
        sim2 = SimulatorSource(scenario=Scenario.NORMAL, count=50, seed=42)

        obs1 = list(sim1.observations())
        obs2 = list(sim2.observations())

        assert len(obs1) == len(obs2) == 50
        for a, b in zip(obs1, obs2):
            assert a.model_dump() == b.model_dump()

    def test_different_seed_different_output(self) -> None:
        """Different seeds must produce different observations."""
        sim1 = SimulatorSource(scenario=Scenario.NORMAL, count=50, seed=42)
        sim2 = SimulatorSource(scenario=Scenario.NORMAL, count=50, seed=99)

        obs1 = list(sim1.observations())
        obs2 = list(sim2.observations())

        # At least some observations should differ
        differences = sum(1 for a, b in zip(obs1, obs2) if a.mq135_raw != b.mq135_raw)
        assert differences > 0

    def test_repeated_iteration_deterministic(self) -> None:
        """Multiple iterations from the same source produce same results."""
        sim = SimulatorSource(scenario=Scenario.NORMAL, count=20, seed=42)
        run1 = [obs.model_dump() for obs in sim.observations()]
        run2 = [obs.model_dump() for obs in sim.observations()]
        assert run1 == run2


class TestSimulatorSourceMode:
    """Verify source mode and provenance."""

    def test_source_mode_is_simulated(self) -> None:
        """Simulator always reports simulated source mode."""
        sim = SimulatorSource()
        assert sim.source_mode == SourceMode.SIMULATED

    def test_repr(self) -> None:
        """Repr includes source mode."""
        sim = SimulatorSource()
        assert "simulated" in repr(sim)


class TestSimulatorSchemaCompatibility:
    """Verify all simulator output validates against the canonical schema."""

    @pytest.mark.parametrize("scenario", list(Scenario))
    def test_all_scenarios_produce_valid_observations(self, scenario: Scenario) -> None:
        """Every scenario must produce schema-valid observations."""
        sim = SimulatorSource(scenario=scenario, count=50, seed=42)
        observations = list(sim.observations())
        assert len(observations) > 0
        for obs in observations:
            # Verify it's a valid RawObservation
            assert isinstance(obs, RawObservation)
            assert obs.device_id
            assert obs.sequence >= 0
            assert obs.device_time_ms >= 0
            assert 0 <= obs.mq135_raw <= 1023


class TestSimulatorScenarios:
    """Verify specific scenario behaviors."""

    def test_normal_count(self) -> None:
        """Normal scenario produces exactly the requested count."""
        sim = SimulatorSource(scenario=Scenario.NORMAL, count=100, seed=42)
        obs = list(sim.observations())
        assert len(obs) == 100

    def test_normal_sequential(self) -> None:
        """Normal scenario has sequential sequence numbers."""
        sim = SimulatorSource(scenario=Scenario.NORMAL, count=50, seed=42)
        obs = list(sim.observations())
        for i, o in enumerate(obs):
            assert o.sequence == i

    def test_spike_has_elevated_readings(self) -> None:
        """Spike scenario has readings well above baseline at known positions."""
        count = 200
        sim = SimulatorSource(scenario=Scenario.SPIKE, count=count, seed=42)
        obs = list(sim.observations())
        spike_indices = {count // 4, count // 2, 3 * count // 4}

        for i in spike_indices:
            assert obs[i].mq135_raw > 500, (
                f"Spike at index {i} should be elevated, got {obs[i].mq135_raw}"
            )

    def test_sustained_anomaly_elevated_region(self) -> None:
        """Sustained anomaly has elevated readings in the middle third."""
        count = 90
        sim = SimulatorSource(scenario=Scenario.SUSTAINED_ANOMALY, count=count, seed=42)
        obs = list(sim.observations())
        anomaly_start = count // 3
        anomaly_end = 2 * count // 3

        # Middle region should have higher MQ135 than edges
        middle_avg = sum(o.mq135_raw for o in obs[anomaly_start:anomaly_end]) / (
            anomaly_end - anomaly_start
        )
        edge_avg = sum(o.mq135_raw for o in obs[:anomaly_start]) / anomaly_start

        assert middle_avg > edge_avg + 50

    def test_invalid_gps_has_no_fix_records(self) -> None:
        """Invalid GPS scenario has records with gps_fix=False."""
        sim = SimulatorSource(scenario=Scenario.INVALID_GPS, count=50, seed=42)
        obs = list(sim.observations())
        no_fix = [o for o in obs if not o.gps_fix]
        assert len(no_fix) > 0
        for o in no_fix:
            assert o.satellites == 0

    def test_packet_gap_has_sequence_jumps(self) -> None:
        """Packet gap scenario has non-sequential sequence numbers."""
        sim = SimulatorSource(scenario=Scenario.PACKET_GAP, count=100, seed=42)
        obs = list(sim.observations())
        sequences = [o.sequence for o in obs]

        # Find gaps
        gaps = [
            sequences[i + 1] - sequences[i]
            for i in range(len(sequences) - 1)
            if sequences[i + 1] - sequences[i] > 1
        ]
        assert len(gaps) > 0, "Should have at least one sequence gap"

    def test_duplicate_packet_has_extra_records(self) -> None:
        """Duplicate packet scenario produces more records than count."""
        sim = SimulatorSource(scenario=Scenario.DUPLICATE_PACKET, count=100, seed=42)
        obs = list(sim.observations())
        # Should have more than 100 due to duplicates
        assert len(obs) > 100

        # Find duplicates by sequence number
        seq_counts: dict[int, int] = {}
        for o in obs:
            seq_counts[o.sequence] = seq_counts.get(o.sequence, 0) + 1
        duplicates = {s: c for s, c in seq_counts.items() if c > 1}
        assert len(duplicates) > 0

    def test_missing_fields_has_none_values(self) -> None:
        """Missing fields scenario has some None environmental values."""
        sim = SimulatorSource(scenario=Scenario.MISSING_FIELDS, count=50, seed=42)
        obs = list(sim.observations())
        has_none_temp = any(o.temperature_c is None for o in obs)
        has_none_humidity = any(o.humidity_pct is None for o in obs)
        has_none_pressure = any(o.pressure_hpa is None for o in obs)
        assert has_none_temp
        assert has_none_humidity
        assert has_none_pressure

    def test_warmup_has_high_initial_readings(self) -> None:
        """Warmup scenario has erratic high readings at start."""
        sim = SimulatorSource(scenario=Scenario.WARMUP, count=50, seed=42)
        obs = list(sim.observations())
        warmup_avg = sum(o.mq135_raw for o in obs[:10]) / 10
        stable_avg = sum(o.mq135_raw for o in obs[20:40]) / 20
        assert warmup_avg > stable_avg + 100

    def test_stale_data_has_old_timestamps(self) -> None:
        """Stale data scenario has some non-advancing device_time_ms."""
        sim = SimulatorSource(scenario=Scenario.STALE_DATA, count=50, seed=42)
        obs = list(sim.observations())
        # Some records should have device_time_ms less than previous
        reversals = 0
        for i in range(1, len(obs)):
            if obs[i].device_time_ms < obs[i - 1].device_time_ms:
                reversals += 1
        assert reversals > 0

    def test_drift_increases_over_time(self) -> None:
        """Drift scenario has gradually increasing MQ135 readings."""
        sim = SimulatorSource(scenario=Scenario.DRIFT, count=200, seed=42)
        obs = list(sim.observations())
        first_quarter_avg = sum(o.mq135_raw for o in obs[:50]) / 50
        last_quarter_avg = sum(o.mq135_raw for o in obs[150:]) / 50
        assert last_quarter_avg > first_quarter_avg + 20


class TestSimulatorJSONL:
    """Test JSONL file output."""

    def test_to_jsonl_creates_valid_file(self, tmp_path: Path) -> None:
        """to_jsonl writes valid JSONL that can be parsed back."""
        output = tmp_path / "test.jsonl"
        sim = SimulatorSource(scenario=Scenario.NORMAL, count=20, seed=42)
        written = sim.to_jsonl(output)

        assert written == 20
        assert output.exists()

        # Read back and validate
        with open(output, encoding="utf-8") as f:
            lines = f.readlines()

        assert len(lines) == 20
        for line in lines:
            data = json.loads(line)
            obs = RawObservation(**data)
            assert obs.device_id == "burnwatch-sim-01"

    def test_to_jsonl_deterministic(self, tmp_path: Path) -> None:
        """Same seed produces identical JSONL files."""
        out1 = tmp_path / "run1.jsonl"
        out2 = tmp_path / "run2.jsonl"

        SimulatorSource(scenario=Scenario.NORMAL, count=10, seed=42).to_jsonl(out1)
        SimulatorSource(scenario=Scenario.NORMAL, count=10, seed=42).to_jsonl(out2)

        assert out1.read_text() == out2.read_text()

    def test_to_jsonl_creates_parent_dirs(self, tmp_path: Path) -> None:
        """to_jsonl creates parent directories if needed."""
        output = tmp_path / "deep" / "nested" / "dir" / "test.jsonl"
        sim = SimulatorSource(scenario=Scenario.NORMAL, count=5, seed=42)
        sim.to_jsonl(output)
        assert output.exists()
