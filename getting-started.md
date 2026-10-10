# BurnWatch — Getting Started

BurnWatch is a local system for receiving CanSat-style environmental telemetry, detecting unusual **relative** MQ135 sensor readings, and guiding a human review of possible burning incidents.

It is designed to support investigation, not automatic accusation. An MQ135 reading is not AQI, PM2.5, a pollutant concentration, or proof of open burning.

This guide gets a local, simulated workflow running. For every command, API endpoint, data field, configuration option, and actual-telemetry workflow, read [how-to.md](how-to.md).

## What you need

- Python 3.11 or newer.
- `pip`.
- A terminal in the `burnwatch` project directory.
- A modern web browser for the local dashboard console.

## 1. Install BurnWatch

From the `burnwatch` directory:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

On macOS or Linux, activate the virtual environment with:

```bash
source .venv/bin/activate
```

If PowerShell does not permit the activation script, use the virtual environment's interpreter directly:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

## 2. Create local configuration

Copy the example configuration file and keep the default simulated data source for the first run:

```powershell
Copy-Item .env.example .env
```

The default database is `data/local/burnwatch.db`. It is created automatically and is ignored by Git.

## 3. Check the installation

```powershell
burnwatch doctor
```

You should see a successful configuration check and an accessible SQLite database. If the `burnwatch` command is not found, the virtual environment is probably not active; use `python -m burnwatch.cli doctor` or reactivate it.

## 4. Run a simple simulated pipeline

This sends 200 deterministic normal readings through parsing, quality checks, anomaly detection, and SQLite storage:

```powershell
burnwatch process
```

Then list any created incidents:

```powershell
burnwatch incidents list
```

Normal telemetry should not create an incident. To generate test telemetry that includes sustained high readings:

```powershell
burnwatch simulate --scenario sustained_anomaly --count 120 --seed 42 --output data\demo\sustained.jsonl
burnwatch process data\demo\sustained.jsonl --source-mode simulated
burnwatch incidents list
```

Any incident created from simulated data is intentionally prevented from being confirmed.

## 5. Start the local API and dashboard console

```powershell
burnwatch api
```

Keep that terminal running. Open [http://127.0.0.1:8000](http://127.0.0.1:8000) in a browser.

The five dashboards open without signing in. They intentionally display only saved CanSat-provenance observations and incidents; simulated test records are not exposed there. The administrator prototype is available from the sidebar for internal Operations testing only.

For a useful dashboard view, load the included Delhi development sample into a local CanSat-mode setup:

1. Change `.env` to `BURNWATCH_DATA_SOURCE=cansat` and restart `burnwatch api` if it is already running.
2. Process the sample:

   ```powershell
   burnwatch process data\demo\delhi_cansat_dashboard_sample.jsonl --source-mode cansat
   ```

3. Refresh the browser. The map, evidence, workflow, and impact views now have five Delhi device locations, with 50 records each.

The included file is generated **development sample input**, not data collected by a physical CanSat. It exercises the same schema and dashboard paths but must never be presented as a real field recording. See [data/demo/README.md](data/demo/README.md) for its locations and provenance details.

The synthetic test-incident action is available only in the administrator Operations utility while the API reports `simulated`. It is disabled in CanSat mode so generated records cannot be mistaken for field data.

For interactive API documentation, open [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs).

## 6. Move from simulated to actual readings

There are two different stages of “actual readings”:

1. **CanSat-schema development sample** — the included Delhi file is safe for visual/dashboard testing but is not field-collected. It can be ingested with `--source-mode cansat` only to exercise the CanSat-provenance UI path in a local development database. Do not confirm or publish resulting cases as actual events.

2. **Recorded actual CanSat data** — a JSONL file recorded by your ground station. This is supported now. Process it as actual data:

   ```powershell
   burnwatch process path\to\recorded-telemetry.jsonl --source-mode cansat
   ```

3. **Live hardware data** — a receiver streaming serial/LoRa data into BurnWatch. The `CanSatLiveSource` adapter connects to the configured serial port (e.g. `COM3` or `/dev/ttyUSB0`), normalizes firmware field aliases, preserves raw payloads, and streams data directly to the pipeline or API via `burnwatch live`.

   Configure the serial port in `.env`:

   ```ini
   BURNWATCH_DATA_SOURCE=cansat
   BURNWATCH_CANSAT_SOURCE=COM3
   BURNWATCH_CANSAT_BAUD=9600
   ```

   Run live serial ingestion directly:

   ```powershell
   burnwatch live --port COM3 --baud 9600
   ```

   Or forward live telemetry to a running BurnWatch API server:

   ```powershell
   burnwatch live --port COM3 --api-url http://127.0.0.1:8000
   ```

   Read [How to use actual CanSat readings](how-to.md#how-to-use-actual-cansat-readings) before conducting field operations.

## Where to go next

- [how-to.md](how-to.md) — full operating guide.
- [instructions.md](instructions.md) — implementation, AWS, security, and deployment work still required.
- [api.md](api.md) — concise REST API reference.
- [testing.md](testing.md) — test commands and testing scope.
