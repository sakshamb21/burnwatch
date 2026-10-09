"""Shared test fixtures for BurnWatch."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

# Canonical sample observation from project spec
CANONICAL_OBSERVATION = {
    "device_id": "burnwatch-cansat-01",
    "sequence": 184,
    "device_time_ms": 368000,
    "mq135_raw": 412,
    "temperature_c": 31.4,
    "humidity_pct": 48.2,
    "pressure_hpa": 1001.3,
    "latitude": 28.75,
    "longitude": 77.12,
    "gps_fix": True,
    "satellites": 7,
}


@pytest.fixture
def canonical_obs() -> dict:
    """Return a copy of the canonical CanSat observation."""
    return CANONICAL_OBSERVATION.copy()


@pytest.fixture
def canonical_obs_json() -> str:
    """Return the canonical observation as a JSON string."""
    return json.dumps(CANONICAL_OBSERVATION)


@pytest.fixture(scope="session")
def fixtures_dir() -> Path:
    """Return the path to the test fixtures directory."""
    return Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session")
def project_root() -> Path:
    """Return the path to the project root directory."""
    return Path(__file__).parent.parent
