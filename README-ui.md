# BurnWatch UI

The BurnWatch UI is a browser-based environmental operations console served by the existing FastAPI application. It uses standard HTML, CSS, and JavaScript without a Node.js build or package-install step. Its map loads Leaflet and OpenStreetMap tiles at runtime, so the map needs normal network access.

## Run locally

Install the Python project, then start the API:

```bash
python -m pip install -e ".[dev]"
burnwatch api
```

Open `http://127.0.0.1:8000`. The API documentation is available at `/docs`.

The UI's five primary dashboards are Incident Map, Event Evidence, Community Reports, Investigation Workflow, and Impact Report. They open without a login. Operations is a separate, non-primary utility route available only after the administrator prototype sign-in.

## Configuration

The UI is served by the same host as the backend and calls relative API URLs. No browser-visible secret or production API key is used. The API data source is configured server-side with `BURNWATCH_DATA_SOURCE`:

```ini
BURNWATCH_DATA_SOURCE=simulated
# or
BURNWATCH_DATA_SOURCE=cansat
```

Restart the API after changing this value. The browser cannot switch the source itself because no safe runtime source-switch API exists. In CanSat mode the UI does not generate synthetic test telemetry.

## Administrator prototype

The sidebar has an **Administrator sign in** action. It opens the visual administrator prototype for Operations and case-action controls; it does not block dashboard viewing. The prototype keeps a mock administrator state in memory for the browser tab, does not retain or transmit the password, and does not claim to authenticate a user. Logout clears this in-memory session.

The backend currently has no authentication or authorization. Therefore the UI's route guards and hidden controls are usability only—not access control. Deployment is blocked until server-enforced authentication, authorization, rate limiting, and audit/security controls are added. See [updates-ui-backend-ui.md](updates-ui-backend-ui.md).

## Data behaviour

- The UI never silently substitutes demo data after an API failure.
- The five primary dashboards filter their fetched observation and incident records to saved CanSat provenance only: `source_mode: "cansat"` and `is_simulated: false`. Simulated records are not rendered there.
- The administrator-only Operations utility can expose simulated records for internal detector testing.
- The Incident Map uses Leaflet with the standard OpenStreetMap tile service and visible OpenStreetMap attribution. It does not prefetch or cache tiles. For production, review the [OpenStreetMap tile usage policy](https://operations.osmfoundation.org/policies/tiles/) and select suitable map hosting if needed.
- Community reports can be submitted through the current API, but the API has no list/read endpoint. The UI may show a newly acknowledged report only for the active browser session and labels it as such.
- Photos, event date/time, report moderation, assignment, inspections, live connection state, and backend source switching are intentionally unavailable because their API contracts do not exist.

## Delhi dashboard sample

Use [data/demo/delhi_cansat_dashboard_sample.jsonl](data/demo/delhi_cansat_dashboard_sample.jsonl) to populate the dashboards with 50 valid schema records at each of five Delhi locations:

```bash
burnwatch process data/demo/delhi_cansat_dashboard_sample.jsonl --source-mode cansat
```

This is generated development input, not physical field telemetry. The complete provenance warning and locations are in [data/demo/README.md](data/demo/README.md). Use a ground-station recording—not this fixture—when working with actual CanSat readings.

## Validation and checks

```bash
# Existing backend suite
pytest

# Python style checks
ruff check src tests

# Syntax check for the browser module (if Node.js is installed)
node --check src/burnwatch/api/static/app.js
```

The required manual UI, accessibility, and security-boundary checks are in [testing-ui.md](testing-ui.md).

## File layout

```text
src/burnwatch/api/static/
├── index.html     # application shell, login and route containers
├── styles.css     # mission-control design tokens and responsive components
└── app.js         # client-side routing, API client, rendering and interaction logic
```
