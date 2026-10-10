# BurnWatch — Product Requirements Document

## Problem Statement

Open waste burning is a significant environmental and health concern in many communities. Current detection relies on manual observation or expensive monitoring stations. Communities need a practical, low-cost tool to systematically flag, investigate, and track suspected burning events.

BurnWatch provides a structured backend for this workflow using observations from a GPS-equipped CanSat with environmental sensors, combined with optional community reports.

## Target Users

1. **Municipal environment officers** investigating reported burning events.
2. **Community volunteers** submitting observations and reports.
3. **Technical operators** managing the CanSat and backend system.
4. **Researchers** analyzing environmental observation data.

## User Stories

- US-01: As an operator, I want to deploy the CanSat and see observations flow into the system.
- US-02: As an operator, I want to generate simulated data to test the system without hardware.
- US-03: As an officer, I want to see candidate incidents flagged by anomaly detection.
- US-04: As an officer, I want to review and confirm or dismiss candidate incidents.
- US-05: As a volunteer, I want to submit a community report about a suspected event.
- US-06: As an officer, I want to track the resolution of confirmed incidents.
- US-07: As a researcher, I want to query historical observations via API.
- US-08: As an operator, I want the system to clearly distinguish simulated from real data.

## Functional Requirements

| ID | Requirement | Priority |
|---|---|---|
| FR-01 | Accept observations from CanSat or simulator via shared schema | Must |
| FR-02 | Validate observation fields with clear rejection reasons | Must |
| FR-03 | Detect relative MQ135 anomalies using rolling median + MAD | Must |
| FR-04 | Create candidate incidents from persistent anomalies | Must |
| FR-05 | Support incident review workflow (confirm, dismiss, resolve) | Must |
| FR-06 | Persist observations and incidents to SQLite | Must |
| FR-07 | Provide REST API for observations and incidents | Must |
| FR-08 | Provide CLI for simulation, replay, processing, inspection | Must |
| FR-09 | Mark all simulated data explicitly | Must |
| FR-10 | Replay recorded JSONL telemetry through the pipeline | Must |
| FR-11 | Track quality flags (GPS, staleness, warmup, gaps) | Must |
| FR-12 | Preserve original observation payload | Must |
| FR-13 | Support community report submission | Should |
| FR-14 | Provide AWS adapter for S3 + DynamoDB | Should |
| FR-15 | Support incident audit history | Must |

## Non-Functional Requirements

| ID | Requirement |
|---|---|
| NF-01 | Deterministic tests without hardware or network |
| NF-02 | Sub-second observation processing latency (local) |
| NF-03 | SQLite database survives process restart |
| NF-04 | No credentials committed to version control |
| NF-05 | Structured logging with timestamps and context |
| NF-06 | Idempotent observation ingestion |

## Acceptance Criteria

- The canonical observation example passes schema validation.
- Simulator generates deterministic output with fixed seeds.
- Anomaly detector flags MQ135 spikes above threshold.
- Candidate incidents cannot become confirmed without human review.
- Replaying the same data produces no duplicates.
- All documented CLI commands execute successfully.
- All documented API endpoints return correct responses.

## MVP Scope

The initial deliverable includes:
- Configuration, observation schema, simulator, parser, quality checks, anomaly detection, incident workflow, SQLite storage, CLI, REST API, and AWS adapter (mocked).

## Explicitly Excluded

- Frontend or web dashboard
- ML model trained on fabricated data
- Official AQI calculation from MQ135
- Production municipal dispatch
- Authentication and notifications
- Microservice architecture

## Scientific Limitations

- MQ135 is a broad-response sensor; readings are relative anomaly indicators, not calibrated measurements.
- BME280 measures temperature, humidity, pressure — not particulates.
- Anomaly detection flags candidates for investigation, not confirmed events.
- No claim of specific pollutant identification.

## Risks and Mitigations

| Risk | Mitigation |
|---|---|
| MQ135 drift over time | Rolling baseline with drift safeguards |
| False positives | Human review required for confirmation |
| Hardware unavailable for testing | Simulator and replay from fixtures |
| AWS costs | Local-first design, AWS optional |
| Data loss | Transactional SQLite writes |

## Success Metrics

- All automated tests pass.
- CLI and API match documentation.
- No simulated data misrepresented as real.
- Incident workflow prevents automated false accusations.
