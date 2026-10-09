"""Unit tests for observation parser and CanSat source adapters."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from burnwatch.ingestion.parser import (
    ParseError,
    SequenceTracker,
    parse_json_line,
    parse_jsonl_file,
)
from burnwatch.models.observation import RawObservation, SourceMode
from burnwatch.sources.cansat import CanSatLiveSource, CanSatReplaySource


class TestParseJsonLine:
    """Tests for parse_json_line function."""

    def test_parse_valid_canonical(self, canonical_obs_json: str) -> None:
        result = parse_json_line(canonical_obs_json, line_number=1)
        assert result.is_valid
        assert not result.is_error
        assert isinstance(result.observation, RawObservation)
        assert result.observation.device_id == "burnwatch-cansat-01"
        assert result.raw_json is not None

    def test_parse_empty_line(self) -> None:
        result = parse_json_line("   ", line_number=5)
        assert not result.is_valid
        assert result.is_error
        assert result.error is not None
        assert result.error.line_number == 5
        assert "Empty line" in result.error.error

    def test_parse_malformed_json_syntax(self) -> None:
        result = parse_json_line("{device_id: invalid_json}", line_number=3)
        assert not result.is_valid
        assert result.is_error
        assert "JSON decode error" in result.error.error

    def test_parse_json_not_an_object(self) -> None:
        result = parse_json_line("[1, 2, 3]", line_number=2)
        assert not result.is_valid
        assert result.is_error
        assert "Expected JSON object" in result.error.error

    def test_parse_validation_error(self, canonical_obs: dict) -> None:
        bad_obs = dict(canonical_obs)
        bad_obs["mq135_raw"] = 9999  # Invalid ADC reading
        result = parse_json_line(json.dumps(bad_obs), line_number=4)
        assert not result.is_valid
        assert result.is_error
        assert "Validation error" in result.error.error

    def test_parse_error_repr(self) -> None:
        err = ParseError(10, "{bad}", "syntax error")
        assert "line=10" in repr(err)


class TestParseJsonlFile:
    """Tests for parse_jsonl_file generator."""

    def test_parse_nonexistent_file(self, tmp_path: Path) -> None:
        results = list(parse_jsonl_file(tmp_path / "nonexistent.jsonl"))
        assert len(results) == 0

    def test_parse_mixed_file(self, tmp_path: Path, canonical_obs: dict) -> None:
        file_path = tmp_path / "mixed.jsonl"
        valid_json_1 = json.dumps(canonical_obs)
        invalid_json = "{bad json syntax"
        obs_bad_field = dict(canonical_obs)
        obs_bad_field["sequence"] = 2
        obs_bad_field["latitude"] = 180.0  # Invalid latitude
        valid_json_2 = json.dumps({**canonical_obs, "sequence": 3})

        file_path.write_text(
            f"{valid_json_1}\n{invalid_json}\n{json.dumps(obs_bad_field)}\n{valid_json_2}\n",
            encoding="utf-8",
        )

        results = list(parse_jsonl_file(file_path))
        assert len(results) == 4
        assert results[0].is_valid
        assert results[0].observation.sequence == canonical_obs["sequence"]
        assert not results[1].is_valid
        assert "JSON decode error" in results[1].error.error
        assert not results[2].is_valid
        assert "Validation error" in results[2].error.error
        assert results[3].is_valid
        assert results[3].observation.sequence == 3


class TestSequenceTracker:
    """Tests for sequence number tracking."""

    def test_first_observation_is_normal(self) -> None:
        tracker = SequenceTracker()
        is_dup, has_gap, gap_size = tracker.check("dev-01", 0)
        assert not is_dup
        assert not has_gap
        assert gap_size == 0

    def test_consecutive_sequences(self) -> None:
        tracker = SequenceTracker()
        tracker.check("dev-01", 0)
        is_dup, has_gap, gap_size = tracker.check("dev-01", 1)
        assert not is_dup
        assert not has_gap
        assert gap_size == 0

    def test_duplicate_detection(self) -> None:
        tracker = SequenceTracker()
        tracker.check("dev-01", 5)
        is_dup, has_gap, gap_size = tracker.check("dev-01", 5)
        assert is_dup
        assert not has_gap
        assert gap_size == 0

    def test_gap_detection(self) -> None:
        tracker = SequenceTracker()
        tracker.check("dev-01", 10)
        is_dup, has_gap, gap_size = tracker.check("dev-01", 15)
        assert not is_dup
        assert has_gap
        assert gap_size == 4  # 11, 12, 13, 14 missing

    def test_multi_device_tracking(self) -> None:
        tracker = SequenceTracker()
        tracker.check("dev-01", 1)
        tracker.check("dev-02", 100)

        is_dup, has_gap, _ = tracker.check("dev-01", 2)
        assert not is_dup
        assert not has_gap

        is_dup, has_gap, _ = tracker.check("dev-02", 101)
        assert not is_dup
        assert not has_gap

    def test_reset(self) -> None:
        tracker = SequenceTracker()
        tracker.check("dev-01", 10)
        tracker.reset("dev-01")
        is_dup, has_gap, _ = tracker.check("dev-01", 10)
        assert not is_dup
        assert not has_gap


class TestCanSatReplaySource:
    """Tests for CanSatReplaySource adapter."""

    def test_source_mode(self, fixtures_dir: Path) -> None:
        source = CanSatReplaySource(fixtures_dir / "canonical_sample.jsonl")
        assert source.source_mode == SourceMode.CANSAT

    def test_file_not_found_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            CanSatReplaySource(tmp_path / "does_not_exist.jsonl")

    def test_observations_replay(self, fixtures_dir: Path) -> None:
        source = CanSatReplaySource(fixtures_dir / "canonical_sample.jsonl")
        records = list(source.observations())
        assert len(records) == 1
        assert records[0].device_id == "burnwatch-cansat-01"
        assert records[0].mq135_raw == 412

    def test_replay_with_invalid_lines_continues(
        self, tmp_path: Path, canonical_obs: dict
    ) -> None:
        file_path = tmp_path / "test_replay.jsonl"
        file_path.write_text(
            f"{json.dumps(canonical_obs)}\n{{invalid}}\n{json.dumps({**canonical_obs, 'sequence': 200})}\n",
            encoding="utf-8",
        )
        source = CanSatReplaySource(file_path)
        records = list(source.observations())
        assert len(records) == 2
        assert records[0].sequence == canonical_obs["sequence"]
        assert records[1].sequence == 200


class TestCanSatLiveSource:
    """Tests for CanSatLiveSource adapter."""

    def test_source_mode(self) -> None:
        source = CanSatLiveSource()
        assert source.source_mode == SourceMode.CANSAT

    def test_unconfigured_raises_connection_error(self) -> None:
        source = CanSatLiveSource()
        with pytest.raises(ConnectionError, match="not configured"):
            list(source.observations())

    def test_configured_unsupported_hardware_raises(self) -> None:
        source = CanSatLiveSource("socket://groundstation:9600")
        with pytest.raises(ConnectionError, match="not implemented"):
            list(source.observations())

    def test_serial_connection_missing_port_raises(self) -> None:
        source = CanSatLiveSource("COM3:9600")
        with pytest.raises(ConnectionError, match="Failed to connect to serial port"):
            list(source.observations())


class TestValidateObservation:
    """Tests for validate_observation cross-field validator."""

    def test_non_dict_rejected(self) -> None:
        from burnwatch.ingestion.validator import validate_observation

        res = validate_observation(["not", "a", "dict"])  # type: ignore[arg-type]
        assert not res.is_valid
        assert "Expected dict" in res.errors[0]

    def test_valid_canonical_passes(self, canonical_obs: dict) -> None:
        from burnwatch.ingestion.validator import validate_observation

        res = validate_observation(canonical_obs)
        assert res.is_valid
        assert res.observation is not None
        assert res.observation.device_id == "burnwatch-cansat-01"

    def test_schema_error_rejected(self, canonical_obs: dict) -> None:
        from burnwatch.ingestion.validator import validate_observation

        bad = {**canonical_obs, "mq135_raw": -10}
        res = validate_observation(bad)
        assert not res.is_valid
        assert len(res.errors) > 0

    def test_gps_fix_with_missing_coords(self, canonical_obs: dict) -> None:
        from burnwatch.ingestion.validator import validate_observation

        bad_gps = {**canonical_obs, "gps_fix": True, "latitude": None}
        res = validate_observation(bad_gps)
        assert res.is_valid  # Still parses into RawObservation
        assert any("coordinates are missing" in err for err in res.errors)

    def test_gps_fix_with_zero_zero_coords(self, canonical_obs: dict) -> None:
        from burnwatch.ingestion.validator import validate_observation

        zero_gps = {**canonical_obs, "gps_fix": True, "latitude": 0.0, "longitude": 0.0}
        res = validate_observation(zero_gps)
        assert res.is_valid
        assert any("may be invalid" in err for err in res.errors)
