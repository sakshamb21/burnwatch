"""Tests for configuration settings."""

from __future__ import annotations

import pytest
from config.settings import DataSource, Settings, StorageBackend


class TestSettings:
    """Tests for Settings configuration loading."""

    def test_default_settings(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Default settings load without error."""
        # Clear any existing env vars to test defaults
        for key in [
            "BURNWATCH_DATA_SOURCE",
            "BURNWATCH_LOG_LEVEL",
            "BURNWATCH_STORAGE",
        ]:
            monkeypatch.delenv(key, raising=False)
        settings = Settings()
        assert settings.data_source == DataSource.SIMULATED
        assert settings.log_level == "INFO"
        assert settings.storage_backend == StorageBackend.SQLITE

    def test_simulated_source(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """BURNWATCH_DATA_SOURCE=simulated is valid."""
        monkeypatch.setenv("BURNWATCH_DATA_SOURCE", "simulated")
        settings = Settings()
        assert settings.data_source == DataSource.SIMULATED

    def test_cansat_source(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """BURNWATCH_DATA_SOURCE=cansat is valid."""
        monkeypatch.setenv("BURNWATCH_DATA_SOURCE", "cansat")
        settings = Settings()
        assert settings.data_source == DataSource.CANSAT

    def test_invalid_source_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Invalid data source raises ValueError."""
        monkeypatch.setenv("BURNWATCH_DATA_SOURCE", "invalid")
        with pytest.raises(ValueError, match="Invalid BURNWATCH_DATA_SOURCE"):
            Settings()

    def test_invalid_storage_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Invalid storage backend raises ValueError."""
        monkeypatch.setenv("BURNWATCH_STORAGE", "postgres")
        with pytest.raises(ValueError, match="Invalid BURNWATCH_STORAGE"):
            Settings()

    def test_case_insensitive_source(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Data source is case-insensitive."""
        monkeypatch.setenv("BURNWATCH_DATA_SOURCE", "SIMULATED")
        settings = Settings()
        assert settings.data_source == DataSource.SIMULATED

    def test_numeric_defaults(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Numeric settings have correct defaults."""
        for key in [
            "BURNWATCH_SIM_SEED",
            "BURNWATCH_SIM_COUNT",
            "BURNWATCH_ANOMALY_THRESHOLD",
        ]:
            monkeypatch.delenv(key, raising=False)
        settings = Settings()
        assert settings.sim_seed == 42
        assert settings.sim_count == 200
        assert settings.anomaly_threshold == 3.0

    def test_aws_not_configured_by_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AWS is not configured when env vars are empty."""
        for key in ["AWS_REGION", "AWS_S3_BUCKET", "AWS_DYNAMODB_TABLE"]:
            monkeypatch.delenv(key, raising=False)
        settings = Settings()
        assert settings.aws_configured is False

    def test_aws_configured_when_all_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """AWS is configured when all three vars are set."""
        monkeypatch.setenv("AWS_REGION", "us-east-1")
        monkeypatch.setenv("AWS_S3_BUCKET", "burnwatch-raw")
        monkeypatch.setenv("AWS_DYNAMODB_TABLE", "burnwatch-incidents")
        settings = Settings()
        assert settings.aws_configured is True

    def test_summary_returns_dict(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """summary() returns a dictionary of settings."""
        settings = Settings()
        summary = settings.summary()
        assert isinstance(summary, dict)
        assert "data_source" in summary
        assert "storage_backend" in summary
        assert "aws_configured" in summary
