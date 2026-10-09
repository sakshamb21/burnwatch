"""BurnWatch central configuration.

Loads settings from environment variables and .env file.
All configuration is validated at startup with sensible defaults.
"""

from __future__ import annotations

import os
from enum import Enum
from pathlib import Path

from dotenv import load_dotenv


def _find_project_root() -> Path:
    p = Path(__file__).resolve()
    for parent in [p, *p.parents]:
        if (parent / "pyproject.toml").exists() or (parent / ".env").exists():
            return parent
    return p.parent


# Load .env file from project root if present
_PROJECT_ROOT = _find_project_root()
_ENV_FILE = _PROJECT_ROOT / ".env"
if _ENV_FILE.exists():
    load_dotenv(_ENV_FILE)


class DataSource(str, Enum):
    """Supported observation data sources."""

    SIMULATED = "simulated"
    CANSAT = "cansat"


class StorageBackend(str, Enum):
    """Supported storage backends."""

    SQLITE = "sqlite"
    AWS = "aws"


def _get_env(key: str, default: str = "") -> str:
    return os.environ.get(key, default)


def _get_env_int(key: str, default: int) -> int:
    raw = os.environ.get(key)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _get_env_float(key: str, default: float) -> float:
    raw = os.environ.get(key)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


class Settings:
    """Application settings loaded from environment variables.

    Attributes are eagerly resolved on construction so that missing or invalid
    configuration is caught early.
    """

    def __init__(self) -> None:
        # Data source
        source_raw = _get_env("BURNWATCH_DATA_SOURCE", "simulated").lower()
        try:
            self.data_source = DataSource(source_raw)
        except ValueError:
            raise ValueError(
                f"Invalid BURNWATCH_DATA_SOURCE={source_raw!r}. "
                f"Must be one of: {', '.join(ds.value for ds in DataSource)}"
            )

        # Logging
        self.log_level = _get_env("BURNWATCH_LOG_LEVEL", "INFO").upper()

        # Storage
        storage_raw = _get_env("BURNWATCH_STORAGE", "sqlite").lower()
        try:
            self.storage_backend = StorageBackend(storage_raw)
        except ValueError:
            raise ValueError(
                f"Invalid BURNWATCH_STORAGE={storage_raw!r}. "
                f"Must be one of: {', '.join(sb.value for sb in StorageBackend)}"
            )

        # Validate AWS configuration when AWS storage is selected
        if self.storage_backend == StorageBackend.AWS:
            if not (_get_env("AWS_REGION") and _get_env("AWS_S3_BUCKET") and _get_env("AWS_DYNAMODB_TABLE")):
                raise ValueError(
                    "BURNWATCH_STORAGE=aws requires AWS_REGION, AWS_S3_BUCKET, "
                    "and AWS_DYNAMODB_TABLE to be set."
                )

        self.database_path = Path(
            _get_env("BURNWATCH_DATABASE_PATH", "data/local/burnwatch.db")
        )
        # Resolve relative paths against project root
        if not self.database_path.is_absolute():
            self.database_path = _PROJECT_ROOT / self.database_path

        # Simulator
        self.sim_seed = _get_env_int("BURNWATCH_SIM_SEED", 42)
        self.sim_count = _get_env_int("BURNWATCH_SIM_COUNT", 200)
        self.sim_interval_ms = _get_env_int("BURNWATCH_SIM_INTERVAL_MS", 2000)

        # CanSat adapter
        self.cansat_source = _get_env("BURNWATCH_CANSAT_SOURCE", "")
        self.cansat_baud = _get_env_int("BURNWATCH_CANSAT_BAUD", 9600)

        # Anomaly detection
        self.anomaly_threshold = _get_env_float("BURNWATCH_ANOMALY_THRESHOLD", 3.0)
        self.anomaly_min_samples = _get_env_int("BURNWATCH_ANOMALY_MIN_SAMPLES", 30)
        self.anomaly_warmup_samples = _get_env_int(
            "BURNWATCH_ANOMALY_WARMUP_SAMPLES", 10
        )

        # API
        self.api_host = _get_env("BURNWATCH_API_HOST", "127.0.0.1")
        self.api_port = _get_env_int("BURNWATCH_API_PORT", 8000)

        # AWS (optional) — AWS_REGION is auto-injected by Lambda runtime
        self.aws_region = _get_env("AWS_REGION", "us-east-1")
        self.aws_s3_bucket = _get_env("AWS_S3_BUCKET", "")
        self.aws_dynamodb_table = _get_env("AWS_DYNAMODB_TABLE", "")

    @property
    def aws_configured(self) -> bool:
        """Return True if minimal AWS settings are provided."""
        return bool(self.aws_region and self.aws_s3_bucket and self.aws_dynamodb_table)

    def summary(self) -> dict:
        """Return a dictionary of current settings for diagnostics."""
        return {
            "data_source": self.data_source.value,
            "log_level": self.log_level,
            "storage_backend": self.storage_backend.value,
            "database_path": str(self.database_path),
            "sim_seed": self.sim_seed,
            "sim_count": self.sim_count,
            "anomaly_threshold": self.anomaly_threshold,
            "anomaly_min_samples": self.anomaly_min_samples,
            "anomaly_warmup_samples": self.anomaly_warmup_samples,
            "cansat_source": self.cansat_source,
            "cansat_baud": self.cansat_baud,
            "api_host": self.api_host,
            "api_port": self.api_port,
            "aws_configured": self.aws_configured,
        }


def get_settings() -> Settings:
    """Create and return validated application settings."""
    return Settings()
