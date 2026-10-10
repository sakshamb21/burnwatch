# BurnWatch — Error Log and Troubleshooting

## Implementation Errors

*Errors are logged here as they are discovered during development. Each entry includes the symptom, root cause, resolution, and regression test.*

### ERR-001: Simulator missing fields overwritten by helper default values
- **Symptom**: In `missing_fields` scenario, observations had randomly generated float values instead of `None`.
- **Root Cause**: `_base_observation` had `if temp is not None:` style logic, but when `temp=None` was explicitly provided as an argument, default parameter evaluation substituted generated random values.
- **Resolution**: Directly instantiate `RawObservation` with explicit `None` fields in `_generate_missing_fields`.
- **Regression Test**: `test_missing_fields_has_none_values` in `tests/unit/test_simulator.py`.

### ERR-002: AnomalyDetector returned stale consecutive_anomalies count on normal sample
- **Symptom**: When an observation dropped below the anomaly threshold, `AnomalyDetectionResult.consecutive_anomalies` still reported `1` instead of `0`.
- **Root Cause**: Local variable `consecutive` was read from state before the threshold check. In the `else` block, `self._consecutive_anomalies[device] = 0` was set, but the local variable was not updated before the return statement.
- **Resolution**: Set `consecutive = 0` inside the `else` block in `AnomalyDetector.process`.
- **Regression Test**: `test_isolated_spike_resets_consecutive` in `tests/unit/test_anomaly.py`.

---

## Troubleshooting Index

### Configuration

| Symptom | Possible Cause | Resolution |
|---|---|---|
| `ValueError: Invalid BURNWATCH_DATA_SOURCE` | Typo in `.env` | Use `simulated` or `cansat` |
| Settings not loading | Missing `.env` file | Copy `.env.example` to `.env` |
| Wrong database path | Relative path resolution | Check `BURNWATCH_DATABASE_PATH` |

### Parsing

| Symptom | Possible Cause | Resolution |
|---|---|---|
| `JSONDecodeError` | Malformed input line | Check JSONL format, one JSON per line |
| Missing fields after parse | CanSat firmware change | Compare against canonical schema |

### Timestamps

| Symptom | Possible Cause | Resolution |
|---|---|---|
| Timestamps in wrong timezone | Missing UTC conversion | All stored times must be UTC |
| `device_time_ms` very large | Interpreted as Unix time | It's a device counter, not epoch |

### GPS

| Symptom | Possible Cause | Resolution |
|---|---|---|
| All observations at (0, 0) | GPS has no fix | Check `gps_fix` flag |
| Coordinates outside valid range | Firmware bug or corruption | Validator rejects out-of-range |

### Baseline / Anomaly

| Symptom | Possible Cause | Resolution |
|---|---|---|
| No anomalies detected | Threshold too high | Lower `BURNWATCH_ANOMALY_THRESHOLD` |
| Everything flagged as anomaly | Insufficient baseline | Increase `BURNWATCH_ANOMALY_MIN_SAMPLES` |
| Constant false positives | MAD near zero | Zero-MAD floor handling should activate |

### Database

| Symptom | Possible Cause | Resolution |
|---|---|---|
| `OperationalError: database is locked` | Concurrent writes | SQLite handles one writer at a time |
| Missing tables | First run | Tables auto-created on startup |
| Duplicate key error | Replayed data | Idempotent ingestion handles this |

### API

| Symptom | Possible Cause | Resolution |
|---|---|---|
| `Connection refused` | Server not running | Start with `burnwatch api` |
| 422 error | Invalid request body | Check Pydantic validation errors |

### AWS

| Symptom | Possible Cause | Resolution |
|---|---|---|
| `NoCredentialsError` | Missing AWS config | Set up `~/.aws/credentials` or env vars |
| `AccessDeniedException` | Insufficient IAM permissions | Check IAM policy |
