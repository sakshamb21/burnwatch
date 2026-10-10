# BurnWatch — Engineering Rules

## Coding Conventions

- Python ≥ 3.11 with type hints on all public interfaces.
- Use `from __future__ import annotations` for forward references.
- Pydantic v2 for data validation.
- Click for CLI commands.
- FastAPI for REST endpoints.
- Modules should be small with single responsibilities.
- Use dependency injection / constructor-based interfaces for sources and storage.

## Modularity

- Each module exposes a clear interface.
- Sources implement `ObservationSource` base class.
- Storage backends implement `StorageBackend` base class.
- Detection is independent of storage and API.
- No circular imports between modules.

## Testing

- All tests deterministic — no hardware or network required for unit/integration.
- Use `pytest` with markers: `unit`, `integration`, `hardware`, `aws`.
- Fixtures use the canonical observation from the project spec.
- Simulator tests use fixed seeds for reproducibility.
- Mock external services, but never claim mocked tests prove real connectivity.
- Add regression tests for every significant bug fix.

## Data Provenance

- Every observation carries a `source_mode`: `simulated` or `cansat`.
- Simulated observations are marked throughout the pipeline.
- Original raw payload is preserved alongside the normalized model.
- Provenance metadata cannot be stripped by downstream processing.

## Simulation / Live Separation

- **Never** silently fall back from `cansat` to `simulated` mode.
- Simulated observations cannot create confirmed incidents.
- Source mode is set by configuration, not auto-detected.
- Tests clearly label which data source they exercise.

## Timestamp Handling

- `device_time_ms` is a device-relative counter, not Unix time.
- `received_at` is the UTC wall-clock time when the backend received the observation.
- All stored timestamps are explicit UTC.
- Do not assume device time is synchronized with wall clock.

## Sensor Validation

- MQ135 raw readings: 0–1023 (10-bit ADC).
- Temperature: -40°C to +85°C (BME280 range).
- Humidity: 0–100%.
- Pressure: 300–1100 hPa.
- Latitude: -90 to +90.
- Longitude: -180 to +180.
- Reject out-of-range values; do not silently clamp.

## GPS Validation

- `gps_fix: false` → coordinates may be stale or default (0,0).
- Invalid GPS does not produce a geolocated event.
- Observations with bad GPS are still stored but flagged.

## Anomaly vs. Incident Semantics

- **Anomaly**: Statistical deviation in MQ135 from rolling baseline.
- **Candidate incident**: Persistent anomaly flagged for review.
- **Confirmed incident**: Human reviewer has validated evidence.
- Anomalies do not automatically become confirmed incidents.
- Sensor anomalies are candidates for investigation, never accusations.

## Incident Confirmation Policy

- Confirmation requires human review.
- Reviewer must provide notes.
- All state transitions are recorded in audit history.
- Dismissed incidents retain their evidence.

## Security and Secrets

- No credentials in source code or version control.
- `.env` is in `.gitignore`.
- API binds to `127.0.0.1` by default (not `0.0.0.0`).
- No unnecessary logging of secrets or personal information.
- Bounded request sizes and sensible timeouts.

## Error Handling

- Catch errors at boundaries, not deep in business logic.
- Use structured logging with context (observation ID, incident ID).
- Never swallow exceptions silently.
- Bounded retry policies for transient failures.
- Preserve enough context to debug failures later.

## Documentation Maintenance

- Update relevant docs after each implementation phase.
- `tasks.md` accurately reflects current status.
- `api.md` matches implemented endpoints.
- `errors.md` contains real discoveries, not hypothetical fixes.

## Definition of Done

A task is complete when:
1. Implementation compiles and passes type checks.
2. Unit tests pass.
3. Integration tests pass (where applicable).
4. Documentation is updated.
5. `tasks.md` reflects the status.
6. No regressions in existing tests.
