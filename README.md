# BurnWatch

**CanSat-Assisted Environmental Incident Investigation System**

BurnWatch is a modular environmental incident reporting and investigation backend that helps communities and municipal teams investigate suspected open-waste-burning events. It combines observations from a GPS-equipped CanSat, relative gas-sensor anomaly detection, optional community-submitted reports, and an incident investigation workflow.

**Workflow:** Observe → Flag → Corroborate → Investigate → Act → Verify → Track recurrence

## Key Features

- **Dual data sources**: Accept both deterministic simulated data and actual CanSat observations via a shared schema.
- **Statistical anomaly detection**: Rolling median + MAD on MQ135 readings with configurable thresholds.
- **Incident investigation workflow**: Candidate → reviewed → confirmed → resolved lifecycle.
- **Local SQLite persistence**: Observations, anomalies, incidents, and audit history.
- **REST API**: FastAPI-based endpoints for observations and incident management.
- **CLI**: Generate synthetic data, replay recordings, run the pipeline, inspect incidents.
- **AWS-ready**: Modular adapter for S3 + DynamoDB behind an interface.
- **Provenance tracking**: Every observation retains its source mode and original payload.

## Hardware

The CanSat uses:
- Arduino Nano
- MQ135 gas sensor (broad-response, not pollutant-specific)
- BME280 environmental sensor (temperature, humidity, pressure)
- NEO-6M GPS module
- SX1278 / RA-02 LoRa transceiver + ground-station receiver

> **Note**: MQ135 provides relative anomaly detection only. Readings are not calibrated AQI, PM2.5, or ppm values.

## Requirements

- Python ≥ 3.11
- pip

## Setup

```bash
# Clone and enter the project
cd burnwatch

# Create virtual environment
python -m venv .venv

# Activate (Windows PowerShell)
.\.venv\Scripts\Activate.ps1

# Activate (Linux/macOS)
source .venv/bin/activate

# Install with dev dependencies
pip install -e ".[dev]"
```

## Configuration

Copy `.env.example` to `.env` and adjust:

```bash
cp .env.example .env
```

Key variables:
| Variable | Default | Description |
|---|---|---|
| `BURNWATCH_DATA_SOURCE` | `simulated` | `simulated` or `cansat` |
| `BURNWATCH_STORAGE` | `sqlite` | Storage backend |
| `BURNWATCH_DATABASE_PATH` | `data/local/burnwatch.db` | SQLite path |
| `BURNWATCH_ANOMALY_THRESHOLD` | `3.0` | MAD multiplier for anomaly detection |
| `BURNWATCH_LOG_LEVEL` | `INFO` | Logging level |

## Simulation Mode

```bash
# Generate 200 normal observations
burnwatch simulate --scenario normal --count 200

# Generate spike scenario with fixed seed
burnwatch simulate --scenario spike --count 200 --seed 42

# All scenarios: normal, drift, spike, sustained_anomaly, invalid_gps,
#   packet_gap, duplicate_packet, stale_data, missing_fields, warmup
```

## Live CanSat Mode

```bash
# Set data source to cansat
export BURNWATCH_DATA_SOURCE=cansat

# Replay recorded telemetry
burnwatch replay data/demo/sample.jsonl

# Process observations through the full pipeline
burnwatch process data/demo/sample.jsonl
```

## CLI Examples

```bash
burnwatch simulate --scenario normal --count 100
burnwatch replay data/demo/sample.jsonl
burnwatch process data/demo/sample.jsonl
burnwatch live --port COM3 --baud 9600
burnwatch incidents list
burnwatch doctor
```

## Local API

```bash
# Start the development server
burnwatch api

# Or directly with uvicorn
uvicorn burnwatch.api.app:app --host 127.0.0.1 --port 8000
```

## Local Dashboard Console

When the API is running, open `http://127.0.0.1:8000` for the basic dashboard
console. Its five public dashboards display only stored CanSat-provenance data;
simulated test results remain in the administrator-only Operations utility.
The console includes a Leaflet/OpenStreetMap incident map, evidence and impact
charts, an administrator prototype entry in the sidebar, a collapsible sidebar,
and light mode. It is still a local testing frontend, not a production
deployment or authorization boundary.

To populate the dashboard with its 250-record, five-location Delhi development
fixture, run:

```bash
burnwatch process data/demo/delhi_cansat_dashboard_sample.jsonl --source-mode cansat
```

This fixture is generated development data, not field-collected CanSat
telemetry. See [data/demo/README.md](data/demo/README.md) before using it.

For deployment, hardware, AWS, security, and operational next steps, see
[instructions.md](instructions.md).

## Running Tests

```bash
# Run all tests
pytest

# Unit tests only
pytest tests/unit/ -v

# Integration tests
pytest tests/integration/ -v

# With coverage
pytest --cov=burnwatch --cov-report=term-missing
```

## AWS Deployment

See [architecture.md](architecture.md) for the AWS integration design. The adapter requires:
- `AWS_REGION`, `AWS_S3_BUCKET`, `AWS_DYNAMODB_TABLE` environment variables
- Standard AWS credential chain (env vars, `~/.aws/credentials`, or IAM role)

AWS functionality is implemented behind an adapter interface and tested with mocks. Live cloud verification requires actual AWS resources and is documented separately.

## Known Limitations

- MQ135 readings are broad-response and cannot identify specific pollutants.
- Anomaly detection flags candidates for human investigation, not confirmed incidents.
- The included frontend is a basic local dashboard console, not a production deployment.
- No authentication in local development mode.
- AWS integration requires manual verification with actual resources.

## Documentation

- [Getting started](getting-started.md) — First local run with simulator, API, and dashboard console
- [How to use BurnWatch](how-to.md) — Detailed guide to every current feature, including actual CanSat telemetry
- [Architecture](architecture.md) — System design, data flow, module responsibilities
- [PRD](prd.md) — Product requirements and acceptance criteria
- [Rules](rules.md) — Engineering policies and domain constraints
- [Tasks](tasks.md) — Implementation tracker
- [API](api.md) — REST endpoint documentation
- [Testing](testing.md) — Test strategy and execution
- [Errors](errors.md) — Debugging log and troubleshooting
- [Next steps](instructions.md) — Hardware, AWS, security, and deployment checklist
- [AWS & Deployment Guide](connectionsnaws.md) — Step-by-step guide to AWS hosting, storage, security, and field linking
- [UI console](README-ui.md) — Frontend run guide, prototype limits, and API behaviour
- [UI architecture](architecture-ui.md) — Console routes, component boundaries, and trust boundaries
- [UI integration log](updates-ui-backend-ui.md) — Required backend changes and production blockers
