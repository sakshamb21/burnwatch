# BurnWatch — Testing Guide

## Test Strategy

BurnWatch uses a layered testing approach:

1. **Unit tests**: Isolated module tests with no external dependencies.
2. **Integration tests**: Tests that exercise storage, pipeline, and API together.
3. **Hardware tests**: Tests requiring physical CanSat connection (marked, skipped by default).
4. **AWS tests**: Tests requiring AWS credentials (marked, skipped by default).

## Directory Structure

```
tests/
├── conftest.py          # Shared fixtures (canonical observation, paths)
├── fixtures/
│   └── canonical_sample.jsonl
├── unit/
│   ├── test_observation.py
│   ├── test_settings.py
│   ├── test_simulator.py
│   ├── test_parser.py
│   ├── test_quality.py
│   ├── test_baseline.py
│   ├── test_anomaly.py
│   ├── test_incidents.py
│   └── test_aws_adapter.py
└── integration/
    ├── test_storage.py
    ├── test_pipeline.py
    └── test_api.py
```

## Commands

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run all tests
pytest

# Run unit tests only
pytest tests/unit/ -v

# Run integration tests
pytest tests/integration/ -v

# Run with coverage
pytest --cov=burnwatch --cov-report=term-missing

# Run specific test file
pytest tests/unit/test_observation.py -v

# Run tests matching pattern
pytest -k "test_canonical" -v
```

## Fixtures

The canonical observation from the project spec is available as:
- `canonical_obs` — Python dict (fresh copy per test)
- `canonical_obs_json` — JSON string
- `fixtures_dir` — Path to `tests/fixtures/`
- `project_root` — Path to project root

## Deterministic Seeds

All simulator tests use fixed random seeds to ensure reproducibility.
Default seed: `42`.

## Validation Scenarios

Tests cover:
- Valid canonical observation
- Missing optional fields (temperature, humidity, pressure)
- Invalid coordinates (lat > 90, lon > 180)
- Invalid sensor ranges (MQ135 > 1023, negative humidity)
- Malformed JSON input
- Missing required fields
- Schema version compatibility
- Source provenance tracking
- Duplicate observation handling
- Sequence gap detection
- GPS validity gating
- Warmup sample exclusion
- Anomaly detection thresholds
- Incident state transitions

## Coverage Goals

Target: >80% coverage on critical paths (models, detection, incidents, pipeline).

Low-priority coverage: CLI formatting, AWS adapter (tested via mocks).

## Known Untested Behavior

- Physical CanSat serial connection (requires hardware)
- Live AWS S3/DynamoDB operations (requires credentials)
- Concurrent multi-user API access (not in MVP scope)
