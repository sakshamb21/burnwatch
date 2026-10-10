# BurnWatch — How To Use the Project

This is the complete operating guide for the current BurnWatch project. It explains what the system does, how to use every available feature, how simulation differs from actual CanSat data, and which capabilities remain preparation work rather than finished production features.

## Contents

1. [Understand the workflow and safety boundary](#understand-the-workflow-and-safety-boundary)
2. [Install, configure, and diagnose](#install-configure-and-diagnose)
3. [Use simulated telemetry](#use-simulated-telemetry)
4. [Use the Delhi dashboard development sample](#use-the-delhi-dashboard-development-sample)
5. [How simulated and actual readings differ](#how-simulated-and-actual-readings-differ)
6. [How to use actual CanSat readings](#how-to-use-actual-cansat-readings)
7. [Use the local dashboard and REST API](#use-the-local-dashboard-and-rest-api)
8. [Understand telemetry fields, quality flags, and detection](#understand-telemetry-fields-quality-flags-and-detection)
9. [Investigate incidents](#investigate-incidents)
10. [Use local storage and manage data safely](#use-local-storage-and-manage-data-safely)
11. [Configure BurnWatch](#configure-burnwatch)
12. [Test and troubleshoot](#test-and-troubleshoot)
13. [Understand AWS and production status](#understand-aws-and-production-status)

## Understand the workflow and safety boundary

BurnWatch follows this sequence:

```text
Receive observation → validate it → add quality flags → build a baseline
→ detect a sustained relative change → create candidate → human review
→ confirm/dismiss → resolve/monitor
```

The system accepts readings from either the deterministic simulator or a CanSat-compatible source. Every saved observation retains its source (`simulated` or `cansat`). The data model also has a raw-payload field for audit provenance; a custom live adapter should populate it, but the current API and JSONL processing paths do not yet save the original serialized input in that field.

### What BurnWatch can conclude

It can identify a reading that is unusually high compared with the recent readings from the same device. Repeated unusual readings can create a **candidate incident** for a person to investigate.

### What BurnWatch cannot conclude

It cannot identify a particular pollutant, calculate AQI or PM2.5, determine the cause of a sensor change, prove that burning occurred, or automatically accuse a person or organization. MQ135 is a broad-response gas sensor. Humidity, temperature, sensor warm-up, placement, and environmental conditions can affect it.

This distinction affects the workflow: only a human reviewer can confirm an incident, notes are mandatory, and simulated incidents can never be confirmed.

## Install, configure, and diagnose

### Install in an isolated environment

Open a terminal in the repository's `burnwatch` directory.

Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

macOS/Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

The editable installation makes the `burnwatch` command available and means local code changes take effect without reinstalling.

### Create `.env`

Copy the safe local defaults:

```powershell
Copy-Item .env.example .env
```

or:

```bash
cp .env.example .env
```

Never commit `.env`; it may later contain deployment details. The project loads it from the repository root on startup.

### Diagnose the project

```bash
burnwatch doctor
```

`doctor` validates configuration, creates/checks the SQLite tables, and reports whether the AWS environment variables are present. It does not contact AWS or prove a cloud deployment works.

### Get command help

```bash
burnwatch --help
burnwatch simulate --help
burnwatch incidents --help
```

## Use simulated telemetry

The simulator is the safest way to learn the project. It produces reproducible records with a fixed seed and uses the same schema as CanSat readings.

### Generate telemetry only

Print twenty normal observations as JSON Lines (one JSON object per line):

```bash
burnwatch simulate --scenario normal --count 20 --seed 42
```

Write a scenario to a file instead:

```bash
burnwatch simulate --scenario spike --count 120 --seed 42 --output data/demo/spike.jsonl
```

The `--output` file is telemetry only. Generating it does not insert it into the database or create incidents.

### Process generated telemetry through the complete pipeline

```bash
burnwatch process data/demo/spike.jsonl --source-mode simulated
```

This parses records, validates them, applies quality checks, calculates anomalies, saves observations in SQLite, and creates candidate incidents when the detection conditions are met.

To run the default normal simulation directly, without a file:

```bash
burnwatch process
```

### Replay versus process

These commands look similar but do different things:

| Command | Reads JSONL | Prints records | Saves records | Runs detection | Creates incidents |
|---|---:|---:|---:|---:|---:|
| `burnwatch replay FILE` | Yes | Yes | No | No | No |
| `burnwatch process FILE` | Yes | Summary only | Yes | Yes | Yes, if conditions are met |
| `burnwatch simulate ...` | Generates | Yes, unless `--output` | No | No | No |

Use `replay` to inspect a recording. Use `process` to make the recording part of the BurnWatch workflow.

### Simulator scenarios

| Scenario | Purpose |
|---|---|
| `normal` | Stable readings with ordinary noise. |
| `drift` | Gradually rising baseline. |
| `spike` | Isolated high readings; useful for checking that one spike is not automatically an incident. |
| `sustained_anomaly` | Sustained high readings; useful for candidate incident testing. |
| `invalid_gps` | Periodic no-fix/invalid GPS records. |
| `packet_gap` | Sequence numbers with missing values. |
| `duplicate_packet` | Repeated device/sequence pairs. |
| `stale_data` | Device time that moves backward or jumps too far. |
| `missing_fields` | Optional environmental values omitted. |
| `warmup` | Early sensor warm-up conditions. |

For a detector test, make the scenario long enough to establish a baseline before the anomaly. The default detector needs ten warm-up records and thirty baseline samples before detection starts; a `sustained_anomaly` run of 120 records is a sensible test.

### Start again with a clean local data set

The database is normally `data/local/burnwatch.db`. Stop the API first. Make a dated backup copy before removing or replacing it, then run `burnwatch doctor` or `burnwatch process` to recreate the schema. Do not delete data that needs to be retained as evidence.

## Use the Delhi dashboard development sample

`data/demo/delhi_cansat_dashboard_sample.jsonl` is a 250-record, five-location Delhi fixture for exercising the public dashboard views. Each location contributes 50 schema-valid records and includes a short elevated-response period so that the detector can create candidate cases.

It is generated development data—not a physical CanSat recording and not evidence of activity in any listed place. The payload schema does not carry a source flag; `--source-mode` assigns the storage provenance.

To load it into a local dashboard database:

```bash
burnwatch process data/demo/delhi_cansat_dashboard_sample.jsonl --source-mode cansat
```

The five dashboard routes filter to CanSat provenance (`source_mode: "cansat"` and `is_simulated: false`), so this command makes the fixture available for UI testing while simulator records stay hidden. This is a limitation of the current two-value source model, not proof that the fixture came from hardware. Keep the fixture in a clearly separated development database, never confirm derived cases as real, and replace it with a ground-station recording for field work. See [data/demo/README.md](data/demo/README.md) for the five locations.

## How simulated and actual readings differ

This is a critical distinction in BurnWatch.

| Topic | Simulated readings | Actual CanSat readings |
|---|---|---|
| Origin | Deterministic generator built into BurnWatch. | Firmware/ground station or a recording produced from it. |
| Provenance saved on each record | `source_mode: "simulated"`, `is_simulated: true`. | `source_mode: "cansat"`, `is_simulated: false`. |
| Purpose | Development, repeatable testing, demonstrations. | Real-world investigation support after hardware validation. |
| Confirmation | Cannot be confirmed; the system returns a conflict. | May be confirmed by a human reviewer after independent evidence. |
| Hardware uncertainty | None; generated data is internally valid by design. | GPS, radio, sensor warm-up, calibration, enclosure, and environmental effects must be assessed. |
| How to use today | `simulate`, `process`, or the page's test button. | Process a recorded JSONL file or submit validated payloads to the API. |

Changing a label is not enough to make data trustworthy. Only select `cansat` for a payload that truly came from the device/ground-station path and whose original record is preserved. The one development-only exception is the clearly labeled Delhi dashboard fixture above: it uses CanSat provenance solely because the current UI needs to exercise its CanSat-only rendering path. It is not actual telemetry and must never be confirmed or represented as such.

## How to use actual CanSat readings

The current project supports **recorded actual telemetry** end to end. It has a defined interface for **live hardware**, but not the physical serial/socket/LoRa receiver implementation. This section separates those modes so that configuration is not mistaken for hardware integration.

### A. Process a recorded CanSat JSONL file — supported now

1. Have the ground station write one decoded telemetry object per line in a UTF-8 `.jsonl` file.
2. Confirm each object follows the required schema shown below.
3. Process it as CanSat provenance:

   ```bash
   burnwatch process path/to/recorded-telemetry.jsonl --source-mode cansat
   ```

4. Review the processing summary for duplicates, quality flags, anomalies, and candidates.
5. Inspect generated candidates:

   ```bash
   burnwatch incidents list --status candidate
   burnwatch incidents show INCIDENT_ID
   ```

`--source-mode cansat` is essential here. Without it, the CLI uses the configured data source. The explicit option makes the command's provenance unambiguous.

You can inspect the file without changing storage:

```bash
burnwatch replay path/to/recorded-telemetry.jsonl --limit 10
```

### B. Submit actual records through the API — supported now

This route is suitable when a ground-station program already has a reliable HTTP client.

1. In `.env`, set the API's default provenance to CanSat:

   ```ini
   BURNWATCH_DATA_SOURCE=cansat
   BURNWATCH_API_HOST=127.0.0.1
   BURNWATCH_API_PORT=8000
   ```

2. Restart the API after changing `.env`:

   ```bash
   burnwatch api
   ```

3. Have the ground station `POST` each decoded JSON payload to `/observations`.

   ```bash
   curl -X POST http://127.0.0.1:8000/observations \
     -H "Content-Type: application/json" \
     -d '{
       "device_id": "burnwatch-cansat-01",
       "sequence": 184,
       "device_time_ms": 368000,
       "mq135_raw": 412,
       "temperature_c": 31.4,
       "humidity_pct": 48.2,
       "pressure_hpa": 1001.3,
       "latitude": 28.75,
       "longitude": 77.12,
       "gps_fix": true,
       "satellites": 7
     }'
   ```

4. Check the API response. A new record returns `201`; retransmitting the same `device_id` and `sequence` returns the saved record with `duplicate_accepted` and `200`.

5. Open the local page or query `/observations` and `/incidents` to inspect outcomes.

The local page does not have a separate “actual” switch. It submits to the same API, and the API applies the server's `BURNWATCH_DATA_SOURCE` setting. Verify the page header says `cansat` before entering real readings.

### C. Connect a live serial, LoRa, or socket receiver

`CanSatLiveSource` connects directly to a ground station via USB-to-UART serial or LoRa receiver. It handles frame buffering, translates firmware field aliases (e.g. `temp_c`, `hum`, `press`, `gas`, `lat`, `lon`, `fix`, `sats`), preserves raw payloads for audit provenance, and reconnects with exponential backoff on transient disconnects.

1. Configure connection settings in `.env`:

   ```ini
   BURNWATCH_DATA_SOURCE=cansat
   BURNWATCH_CANSAT_SOURCE=COM3
   BURNWATCH_CANSAT_BAUD=9600
   ```

2. Run live ingestion directly into the local SQLite database and anomaly pipeline:

   ```bash
   burnwatch live --port COM3 --baud 9600
   ```

   To stop automatically after receiving N records (useful in tests or field passes):

   ```bash
   burnwatch live --port COM3 --limit 50
   ```

3. Alternatively, stream live serial telemetry to a running local or remote BurnWatch API server:

   ```bash
   burnwatch live --port COM3 --api-url http://127.0.0.1:8000
   ```

4. Check connection and telemetry health:

   - Query `GET /telemetry/status` or `GET /health` on the API.
   - Run `burnwatch doctor` to verify serial configuration.
   - Python code can access `source.health()` directly for real-time telemetry stats (packets received, valid, corrupt, last packet time, state).

### Actual-data readiness checklist

Before using actual readings in a field investigation:

- Validate the firmware payload against the required schema.
- Confirm that `device_time_ms` is a monotonic device counter, not a Unix timestamp.
- Ensure device IDs do not collide between devices.
- Allow sensor and detector warm-up before interpreting results.
- Confirm that GPS fix and satellite count represent the ground-station/device's real state.
- Record calibration conditions, placement, firmware version, and receiver timestamps.
- Preserve original telemetry and data-quality flags.
- Corroborate candidates with human observation or other permitted evidence before confirming them.

## Use the local dashboard and REST API

### Start the API

```bash
burnwatch api
```

Optional development options:

```bash
burnwatch api --host 127.0.0.1 --port 8000 --reload
```

Keep the default loopback host (`127.0.0.1`) for local development. Binding to a broader network interface is not a security deployment strategy; the current API has no authentication.

Open these URLs while it runs:

- `http://127.0.0.1:8000` — local dashboard console.
- `http://127.0.0.1:8000/docs` — generated FastAPI/OpenAPI documentation.
- `http://127.0.0.1:8000/health` — health/configuration summary.

### Use the dashboard console

The console is a basic frontend intended to exercise the existing backend; it is not a production-ready deployment. Its five primary dashboards are public and show only saved CanSat-provenance observations/incidents. Simulated records are intentionally absent from those views.

| Console area | What it does |
|---|---|
| Incident Map | Leaflet/OpenStreetMap map with a relative CanSat anomaly heat overlay, donut/bar composition charts, filters, and a visible-event list. The overlay is not AQI or pollutant concentration. |
| Event Evidence | Case/device selection, MQ135 relative-response chart, table equivalent, data-quality context, and uncertainty caveats. |
| Community Reports | Calls `POST /reports`; successful acknowledgements are visible only in the current browser because no list endpoint exists. |
| Investigation Workflow | Lists CanSat cases, filters them, opens audit detail, and exposes transitions only after administrator-prototype sign-in. |
| Impact Report | Card/block metrics plus backend-status and case-creation bar charts, with unsupported metrics marked unavailable. |
| Administrator Operations | Sidebar sign-in opens this internal prototype utility for current source/health, individual telemetry submission, simulated test generation, and unfiltered internal observations. |

Use the sidebar's **Light mode** button for the alternate colour scheme and the desktop collapse button to reduce the sidebar. The administrator sign-in is visual only: passwords are neither sent nor stored, and its browser-side guard cannot secure the API. The test generator is available only when the API reports `simulated`; its records remain out of the five dashboards and cannot be confirmed.

### API endpoints

All current endpoints are at the API root; `/api/v1` is only planned.

| Method and path | Purpose |
|---|---|
| `GET /` | Serves the local dashboard console. |
| `GET /health` | Returns service status, version, configured data source, and storage type. |
| `POST /observations` | Validates and processes one telemetry object. |
| `GET /observations?limit=50&offset=0&device_id=...` | Lists saved observations. `limit` is 1–500. |
| `POST /reports` | Creates a community report. |
| `GET /incidents?status=...&limit=20&offset=0` | Lists incidents. `limit` is 1–100. |
| `GET /incidents/{incident_id}` | Returns one incident with its audit history. |
| `POST /incidents/{incident_id}/review` | Starts review, confirms, or dismisses a candidate. |
| `POST /incidents/{incident_id}/status` | Moves an incident through later lifecycle states. |

### API request examples

Health:

```bash
curl http://127.0.0.1:8000/health
```

List recent observations:

```bash
curl "http://127.0.0.1:8000/observations?limit=25&device_id=burnwatch-cansat-01"
```

Submit a community report:

```bash
curl -X POST http://127.0.0.1:8000/reports \
  -H "Content-Type: application/json" \
  -d '{
    "reporter_name": "Citizen John",
    "description": "Thick smoke rising from an empty plot.",
    "contact": "555-0199",
    "latitude": 28.71,
    "longitude": 77.11
  }'
```

Start a review:

```bash
curl -X POST http://127.0.0.1:8000/incidents/INCIDENT_ID/review \
  -H "Content-Type: application/json" \
  -d '{"reviewer":"officer_1", "action":"under_review", "notes":"Reviewing field evidence."}'
```

Confirm an actual CanSat candidate:

```bash
curl -X POST http://127.0.0.1:8000/incidents/INCIDENT_ID/review \
  -H "Content-Type: application/json" \
  -d '{"reviewer":"officer_1", "action":"confirm", "notes":"Confirmed after permitted field verification."}'
```

The last request is rejected for a simulated incident. That is expected.

Mark a confirmed incident resolved:

```bash
curl -X POST http://127.0.0.1:8000/incidents/INCIDENT_ID/status \
  -H "Content-Type: application/json" \
  -d '{"status":"resolved", "reviewer":"officer_1", "notes":"Action completed and documented."}'
```

## Understand telemetry fields, quality flags, and detection

### Canonical telemetry object

`POST /observations`, JSONL recordings, and `burnwatch process` expect this shape:

```json
{
  "device_id": "burnwatch-cansat-01",
  "sequence": 184,
  "device_time_ms": 368000,
  "mq135_raw": 412,
  "temperature_c": 31.4,
  "humidity_pct": 48.2,
  "pressure_hpa": 1001.3,
  "latitude": 28.75,
  "longitude": 77.12,
  "gps_fix": true,
  "satellites": 7
}
```

Required fields are `device_id`, `sequence`, `device_time_ms`, and `mq135_raw`. Environmental and GPS-position fields are optional, but their absence has quality consequences.

| Field | Meaning and rules |
|---|---|
| `device_id` | Non-empty stable device identifier. Do not reuse it for unrelated hardware. |
| `sequence` | Non-negative packet number. The `(device_id, sequence)` pair makes ingestion idempotent. |
| `device_time_ms` | Non-negative device-relative counter in milliseconds; it is not a Unix timestamp. |
| `mq135_raw` | 10-bit ADC reading, integer 0–1023. It is a relative sensor signal, not a concentration. |
| `temperature_c` | Optional BME280 temperature, -40 to 85 °C. |
| `humidity_pct` | Optional relative humidity, 0 to 100. |
| `pressure_hpa` | Optional pressure, 300 to 1100 hPa. |
| `latitude` / `longitude` | Optional GPS coordinates. Latitude must be -90 to 90, longitude -180 to 180. |
| `gps_fix` | Whether the device had a GPS fix. |
| `satellites` | Non-negative count of satellites observed. |

Unknown fields are rejected. Invalid ranges result in an API `422` response rather than silent correction.

### Quality flags

BurnWatch stores observations even when they have a quality issue, then attaches flags so a reviewer can interpret them correctly.

| Flag | Meaning |
|---|---|
| `warmup` | One of the first ten observations for this device since the process began. |
| `gps_no_fix` | `gps_fix` is false. |
| `gps_invalid_coords` | GPS claims a fix but coordinates are missing or `(0, 0)`. |
| `low_satellites` | GPS claims a fix but fewer than four satellites are reported. |
| `stale` | Device time moved backward or jumped more than 30 seconds. |
| `duplicate` | The same sequence was seen again in the running process. Storage also rejects the duplicate pair. |
| `sequence_gap` | A packet number appears to be missing. |
| `missing_environmental` | Temperature, humidity, or pressure is absent. |
| `sensor_out_of_range` | Reserved quality-flag vocabulary; out-of-range values are currently rejected by schema validation before storage. |

Flags are evidence about data quality, not an automatic deletion rule. Always consider them during review.

### Detection behaviour

For each device, the detector:

1. excludes its first ten samples as warm-up;
2. builds a rolling baseline from normal MQ135 readings;
3. waits until it has thirty baseline samples;
4. computes deviation using a robust rolling median and Median Absolute Deviation (MAD);
5. flags readings at or above a score of 3.0;
6. creates a candidate only after three consecutive anomalous readings;
7. applies a five-sample cooldown before another candidate for that device.

An anomalous reading is not added to the baseline, which limits one sharp change from immediately shifting the normal reference.

### Important current configuration limitation

`.env` includes `BURNWATCH_ANOMALY_THRESHOLD`, `BURNWATCH_ANOMALY_MIN_SAMPLES`, and `BURNWATCH_ANOMALY_WARMUP_SAMPLES`. They are read and shown by `burnwatch doctor`, but the current CLI/API construction of `PipelineProcessor` uses its built-in detector defaults rather than passing these environment values into the detector. Treat the actual current values above as authoritative until that wiring is implemented and verified.

## Investigate incidents

### List and inspect candidates

```bash
burnwatch incidents list
burnwatch incidents list --status candidate
burnwatch incidents show INCIDENT_ID
```

`show` accepts a full ID or a unique initial prefix. It displays source mode, location, peak MQ135 reading, score, reviewer, notes, evidence count, and full audit history.

### Incident lifecycle

```text
candidate → under_review → confirmed → resolved → monitoring
     └────────────────→ dismissed
monitoring → resolved or candidate
```

The valid transitions are:

| Current status | Allowed next status |
|---|---|
| `candidate` | `under_review`, `dismissed`; a confirm action passes through `under_review`. |
| `under_review` | `confirmed`, `dismissed`. |
| `confirmed` | `resolved`. |
| `resolved` | `monitoring`. |
| `monitoring` | `resolved`, `candidate`. |
| `dismissed` | No further transition. |

Every transition needs an actor/reviewer and non-empty notes. The system stores it in immutable-style audit history.

### Review from the CLI

```bash
burnwatch incidents review INCIDENT_ID \
  --action under_review \
  --reviewer "officer_1" \
  --notes "Checking reported location and reviewing telemetry."
```

To dismiss a false alert:

```bash
burnwatch incidents review INCIDENT_ID \
  --action dismiss \
  --reviewer "officer_1" \
  --notes "No corroborating evidence; sensor disturbance recorded."
```

Use `confirm` only after permitted, independent human verification, and only for `cansat` (actual) provenance. A simulated candidate is intentionally rejected.

### Community reports

Community reports are optional corroborating information. The API stores reporter name, description, optional contact, and optional coordinates in SQLite. They do not automatically create or confirm an incident. Treat contact information as personal data and restrict access/retention appropriately before any deployment.

## Use local storage and manage data safely

### What is stored

The default SQLite database stores:

- normalized observations, quality flags, and anomaly results; the schema includes a raw-payload field, but the current API/JSONL routes do not yet populate it;
- quality flags and anomaly results;
- incidents, lifecycle status, evidence links, reviewer/notes, and audit history;
- community reports.

The default path is `data/local/burnwatch.db`. Relative paths are resolved from the project root. SQLite tables are created automatically.

### Idempotency and duplicates

The combination of `device_id` and `sequence` is unique. Sending the same pair again does not overwrite the original observation. This protects receiver retries, but it also means a faulty device that restarts sequence numbers with the same device ID will create collisions. Give each physical device a stable unique ID and define its restart/sequence policy before field use.

### Backup and retention

For local experimentation, stop writes before copying the SQLite database. For any data used as evidence or containing personal reports, establish a backup, encryption, retention, access-control, and restore policy before operating outside a controlled development environment.

## Configure BurnWatch

Put settings in `.env` or set them in the environment before starting the command. Restart the API after changing its settings.

| Variable | Default | Current purpose |
|---|---|---|
| `BURNWATCH_DATA_SOURCE` | `simulated` | API provenance: `simulated` or `cansat`. Does not create a live connection. |
| `BURNWATCH_LOG_LEVEL` | `INFO` | CLI processing log verbosity. |
| `BURNWATCH_STORAGE` | `sqlite` | Only accepted storage selector today. |
| `BURNWATCH_DATABASE_PATH` | `data/local/burnwatch.db` | SQLite file path. |
| `BURNWATCH_SIM_SEED` | `42` | Default seed for `burnwatch process` with no file. |
| `BURNWATCH_SIM_COUNT` | `200` | Number of default simulated observations. |
| `BURNWATCH_SIM_INTERVAL_MS` | `2000` | Simulated device-time interval. |
| `BURNWATCH_CANSAT_SOURCE` | empty | Intended live connection string; not consumed by a finished live adapter yet. |
| `BURNWATCH_CANSAT_BAUD` | `9600` | Intended live serial baud rate; not used by a finished live adapter yet. |
| `BURNWATCH_ANOMALY_THRESHOLD` | `3.0` | Read by settings, but not yet passed to the CLI/API detector; see the limitation above. |
| `BURNWATCH_ANOMALY_MIN_SAMPLES` | `30` | Same wiring limitation. |
| `BURNWATCH_ANOMALY_WARMUP_SAMPLES` | `10` | Same wiring limitation. |
| `BURNWATCH_API_HOST` | `127.0.0.1` | Local API bind host. |
| `BURNWATCH_API_PORT` | `8000` | Local API port. |
| `AWS_REGION` | empty | AWS adapter configuration only; does not switch current app storage. |
| `AWS_S3_BUCKET` | empty | AWS raw-object bucket configuration only. |
| `AWS_DYNAMODB_TABLE` | empty | AWS incident-table configuration only. |

## Test and troubleshoot

### Run tests

```bash
pytest
pytest tests/unit/ -v
pytest tests/integration/ -v
pytest --cov=burnwatch --cov-report=term-missing
```

Tests cover models, configuration, simulator behaviour, parser, quality checks, baseline/detection, incident lifecycle, storage, pipeline, API, and the temporary page assets. Physical hardware and live AWS tests need a deliberately configured external environment and are not proven by the local suite.

### Common problems

| Symptom | Likely cause and action |
|---|---|
| `burnwatch` is not recognized | Activate `.venv`, then reinstall with `python -m pip install -e ".[dev]"`. |
| API connection refused | Run `burnwatch api` and use the configured host/port. |
| HTTP `422` | Check required fields, numeric ranges, and field names. The response identifies the rejected field. |
| Expected actual data appears simulated | Set `BURNWATCH_DATA_SOURCE=cansat` before starting the API, or run file processing with `--source-mode cansat`. |
| Nothing becomes anomalous | Ensure enough normal baseline samples precede the change; inspect flags and use sustained changes rather than one spike. |
| Simulated incident cannot confirm | Expected safeguard. Use a verified CanSat-recorded/API input for an actual workflow. |
| Duplicate accepted | Expected retry protection: same `device_id` + `sequence` was already stored. |
| Database locked | SQLite supports one writer at a time. Stop competing writers or move to a designed production storage architecture. |
| `CanSat live source not configured` or `not implemented` | The live adapter is a contract only. Use recorded JSONL/API posting or implement the ground-station connection layer. |

For additional historical debugging notes, see [errors.md](errors.md).

## Understand AWS and production status

BurnWatch includes an `AWSStorageAdapter` that can write observation objects to S3 and incidents to DynamoDB, plus mock-based tests. This is not yet a complete deployed service:

- `BURNWATCH_STORAGE` currently only accepts `sqlite`.
- The API and CLI construct local SQLite storage; setting AWS variables does not redirect production writes to S3/DynamoDB.
- The AWS adapter uses list/scan patterns that need production-scale key/index design before use at volume.
- No infrastructure as code, API Gateway/Lambda packaging, authentication/authorization, CORS policy, network design, live cloud verification, alarms, backups, or incident runbooks are supplied as a finished deployment.

Do not expose the current unauthenticated local API to the internet. Use [instructions.md](instructions.md) as the cloud, security, deployment, operational, and hardware implementation checklist.

## Documentation map

| Document | Use it for |
|---|---|
| [getting-started.md](getting-started.md) | First local run. |
| [how-to.md](how-to.md) | Detailed operational guide (this document). |
| [api.md](api.md) | Compact API reference. |
| [architecture.md](architecture.md) | Component and data-flow design. |
| [testing.md](testing.md) | Test strategy and commands. |
| [instructions.md](instructions.md) | Work needed for hardware, AWS, security, and production. |
| [errors.md](errors.md) | Known troubleshooting notes. |
