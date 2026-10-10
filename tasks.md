# BurnWatch — Task Tracker

## Phase 1: Bootstrap Repository and Documents

| ID | Task | Dependencies | Status | Acceptance Criteria | Tests | Notes |
|---|---|---|---|---|---|---|
| T-001 | Create directory structure | — | DONE | All directories exist | — | Created src/, tests/, config/, data/ |
| T-002 | Create pyproject.toml | — | DONE | Package metadata valid | — | Configured hatchling, deps, scripts |
| T-003 | Create .gitignore, .env.example | — | DONE | Files exist, secrets excluded | — | Ignored .env, *.db, pycache |
| T-004 | Create config/settings.py | — | DONE | Settings load from env | unit | Settings class with validation |
| T-005 | Create package __init__.py files | T-001 | DONE | Package importable | unit | All modules initialised |
| T-006 | Create CLI entry point | T-005 | DONE | `burnwatch --help` works | unit | Click CLI group in cli.py |
| T-007 | Create all 8 documentation files | — | DONE | Files exist and are accurate | — | prd, arch, rules, api, etc. |
| T-008 | Create test conftest and fixtures | T-001 | DONE | Canonical fixture available | unit | conftest.py with canonical sample |
| T-009 | Install package and verify import | T-002,T-005 | DONE | `import burnwatch` works | unit | Editable install in venv |
| T-010 | Verify test runner starts | T-008 | DONE | `pytest` runs without error | unit | pytest running 181 tests |
| T-011 | Git initial commit | T-001–T-010 | DONE | Clean commit with all files | — | Staged and committed |

## Phase 2: Configuration and Observation Schema

| ID | Task | Dependencies | Status | Acceptance Criteria | Tests | Notes |
|---|---|---|---|---|---|---|
| T-020 | Implement observation model | T-009 | DONE | Canonical sample validates | unit | RawObservation & NormalizedObservation |
| T-021 | Add validation for coordinates | T-020 | DONE | Out-of-range rejected | unit | Lat [-90,90], Lon [-180,180] |
| T-022 | Add validation for sensor ranges | T-020 | DONE | Out-of-range rejected | unit | MQ135 [0,1023], BME280 ranges |
| T-023 | Handle optional fields | T-020 | DONE | Missing optionals accepted | unit | Temp, humidity, pressure optional |
| T-024 | Handle malformed input | T-020 | DONE | Clear validation errors | unit | Pydantic ValidationError on bad types |
| T-025 | Add source provenance metadata | T-020 | DONE | Source mode tracked | unit | SourceMode enum & is_simulated |
| T-026 | Test configuration module | T-009 | DONE | Valid/invalid env tested | unit | 10 settings unit tests |

## Phase 3: Deterministic Simulator

| ID | Task | Dependencies | Status | Acceptance Criteria | Tests | Notes |
|---|---|---|---|---|---|---|
| T-030 | Implement source base class | T-020 | DONE | Interface defined | — | ObservationSource base class |
| T-031 | Implement simulator | T-030 | DONE | All 10 scenarios work | unit | SimulatorSource with 10 scenarios |
| T-032 | Test determinism | T-031 | DONE | Same seed = same output | unit | Seeded random generation |
| T-033 | Test JSONL output | T-031 | DONE | Valid JSONL generated | unit | `to_jsonl` method |
| T-034 | Test schema compatibility | T-031,T-020 | DONE | All records validate | unit | 29 simulator tests pass |

## Phase 4: Parser, Replay, and Live Adapter

| ID | Task | Dependencies | Status | Acceptance Criteria | Tests | Notes |
|---|---|---|---|---|---|---|
| T-040 | Implement parser | T-020 | DONE | JSON/JSONL parsing works | unit | parse_json_line & parse_jsonl_file |
| T-041 | Implement CanSat adapter | T-030 | DONE | Replay from JSONL works | unit | CanSatReplaySource & CanSatLiveSource |
| T-042 | Handle malformed lines | T-040 | DONE | Bad lines logged, not crash | unit | ParseError structured logging |
| T-043 | Detect duplicates and gaps | T-040 | DONE | Sequence tracking works | unit | SequenceTracker device tracking |
| T-044 | Implement live serial connection | T-041 | DONE | Serial streaming, reconnect, field alias normalization | unit | SerialConnection, CanSatLiveSource, CLI `live` |

## Phase 5: Data Quality and Provenance

| ID | Task | Dependencies | Status | Acceptance Criteria | Tests | Notes |
|---|---|---|---|---|---|---|
| T-050 | Implement quality checks | T-020 | DONE | All flags computed | unit | QualityChecker with 9 QualityFlags |
| T-051 | GPS validity gating | T-050 | DONE | Invalid GPS flagged | unit | No-fix, invalid coords, low sats |
| T-052 | Staleness detection | T-050 | DONE | Old data flagged | unit | Time gap & retrograde checks |
| T-053 | Warmup detection | T-050 | DONE | Early samples flagged | unit | First N samples flagged WARMUP |
| T-054 | Provenance preservation | T-025 | DONE | Source mode survives pipeline | integration | SourceMode retained in NormalizedObservation |

## Phase 6: Baseline and Anomaly Detection

| ID | Task | Dependencies | Status | Acceptance Criteria | Tests | Notes |
|---|---|---|---|---|---|---|
| T-060 | Implement baseline tracker | T-020 | DONE | Rolling median computed | unit | RollingBaseline with median & MAD |
| T-061 | Implement anomaly detector | T-060 | DONE | MAD-based detection works | unit | AnomalyDetector with score calculation |
| T-062 | Test spike detection | T-061 | DONE | Spikes flagged correctly | unit | Score above threshold flagged |
| T-063 | Test sustained anomaly | T-061 | DONE | Persistence tracked | unit | Candidate incident triggered |
| T-064 | Test warmup exclusion | T-061 | DONE | No detection during warmup | unit | Warmup samples excluded |
| T-065 | Test zero MAD handling | T-061 | DONE | Floor applied | unit | min_mad_floor applied |

## Phase 7: Incident Domain Model and Workflow

| ID | Task | Dependencies | Status | Acceptance Criteria | Tests | Notes |
|---|---|---|---|---|---|---|
| T-070 | Implement incident model | — | DONE | State machine defined | unit | Incident & IncidentHistoryEntry |
| T-071 | Implement incident service | T-070 | DONE | CRUD + transitions work | unit | IncidentService lifecycle methods |
| T-072 | Test valid transitions | T-071 | DONE | All valid paths tested | unit | candidate -> under_review -> confirmed -> resolved |
| T-073 | Test invalid transitions | T-071 | DONE | Invalid transitions rejected | unit | InvalidTransitionError raised |
| T-074 | Test audit history | T-071 | DONE | All changes recorded | unit | History preserved with actor & notes |

## Phase 8: Local Storage

| ID | Task | Dependencies | Status | Acceptance Criteria | Tests | Notes |
|---|---|---|---|---|---|---|
| T-080 | Implement storage interface | — | DONE | Abstract base defined | — | StorageBackend abstract class |
| T-081 | Implement SQLite storage | T-080 | DONE | Tables created, CRUD works | integration | LocalStorage with 6 tables |
| T-082 | Test duplicate prevention | T-081 | DONE | No duplicates on replay | integration | UNIQUE(device_id, sequence) |
| T-083 | Test restart persistence | T-081 | DONE | Data survives restart | integration | File-backed SQLite verified |

## Phase 9: Processing Pipeline and CLI

| ID | Task | Dependencies | Status | Acceptance Criteria | Tests | Notes |
|---|---|---|---|---|---|---|
| T-090 | Implement pipeline processor | T-050,T-061,T-071,T-081 | DONE | Full pipeline works | integration | PipelineProcessor end-to-end |
| T-091 | Implement CLI commands | T-090 | DONE | All commands work | integration | doctor, simulate, replay, process, incidents, api |
| T-092 | Test CLI exit codes | T-091 | DONE | Error exits non-zero | unit | CliRunner testing valid/invalid calls |

## Phase 10: Local REST API

| ID | Task | Dependencies | Status | Acceptance Criteria | Tests | Notes |
|---|---|---|---|---|---|---|
| T-100 | Implement API endpoints | T-090 | DONE | All endpoints respond | integration | FastAPI app in api/app.py |
| T-101 | Test valid requests | T-100 | DONE | Correct responses | integration | /health, /observations, /incidents, /reports |
| T-102 | Test error handling | T-100 | DONE | Proper HTTP codes | integration | 404, 409, 422 tested |
| T-103 | Test idempotent ingestion | T-100 | DONE | Duplicates handled | integration | Duplicate submission returns 200 duplicate_accepted |

## Phase 11: AWS Adapter

| ID | Task | Dependencies | Status | Acceptance Criteria | Tests | Notes |
|---|---|---|---|---|---|---|
| T-110 | Implement AWS adapter | T-080 | DONE | Adapter code complete | — | AWSStorageAdapter (S3 + DynamoDB) |
| T-111 | Mock AWS tests | T-110 | DONE | Mocked operations pass | unit | 7 mocked unit tests pass |
| T-112 | Document deployment | T-110 | DONE | Commands documented | — | Documented in architecture.md & README |

## Phase 12: End-to-End Tests

| ID | Task | Dependencies | Status | Acceptance Criteria | Tests | Notes |
|---|---|---|---|---|---|---|
| T-120 | E2E simulated pipeline | T-090 | DONE | Full flow passes | integration | test_e2e_simulation_to_dismissal |
| T-121 | E2E recorded replay | T-090 | DONE | Replay flow passes | integration | test_e2e_cansat_full_lifecycle |
| T-122 | Generate validation report | T-120,T-121 | DONE | Report accurate | — | 181 passed tests, 90% coverage |

## Phase 13: Final Documentation

| ID | Task | Dependencies | Status | Acceptance Criteria | Tests | Notes |
|---|---|---|---|---|---|---|
| T-130 | Audit all 8 docs | T-120 | DONE | Docs match implementation | — | prd, arch, rules, api, errors, tasks, testing, README |
| T-131 | Verify clean install | T-130 | DONE | Fresh install works | — | Package and CLI functional |
| T-132 | Final tasks.md update | T-131 | DONE | All statuses accurate | — | Complete tracker updated |
