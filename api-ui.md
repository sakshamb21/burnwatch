# BurnWatch UI API Contract

The UI uses the existing API without changing its contracts. Calls are same-origin relative URLs and use JSON.

## Implemented endpoints used by the UI

| Endpoint | UI use | Authentication today |
|---|---|---|
| `GET /health` | API health, configured data source, storage label. | None (development only). |
| `GET /observations` | Map/evidence/operations tables and client-side metrics. | None (development only). |
| `POST /observations` | Operations telemetry form. | None (development only). |
| `GET /incidents` | Map/workflow/impact queues and metrics. | None (development only). |
| `GET /incidents/{id}` | Evidence/workflow drawer and audit history. | None (development only). |
| `POST /incidents/{id}/review` | Candidate review actions. | None (development only). |
| `POST /incidents/{id}/status` | Existing lifecycle transition actions. | None (development only). |
| `POST /reports` | Community report form. | None (development only). |

The UI handles validation (`422`), conflict/invalid transition (`409`), missing resource (`404`), authentication (`401`), authorization (`403`), network failure, and server error distinctly. The backend does not currently emit `401` or `403`; their UI handling is future-proofing, not proof of access control. After each successful list fetch, the five primary dashboards retain only records with `source_mode: "cansat"` and `is_simulated: false`; the administrator Operations utility retains the unfiltered list for internal testing.

## Required production permission matrix

| Role | UI prototype behaviour | Required server enforcement before deployment |
|---|---|---|
| Public/community reporter | Reads the five dashboard views and can use the report form. | May submit only to a public, rate-limited report endpoint and read only its authorized acknowledgement. |
| Viewer/analyst | Same public dashboard view in this prototype. | Read only records explicitly permitted to that identity. |
| Administrator prototype | UI exposes Operations and existing incident-review controls. | Validate case-level assignment/role and audit every state change. |
| Operations operator | Not separately modeled by the current UI. | Permit only explicit operational/source controls; never arbitrary serial access. |
| Administrator | Visual state only; no backend authorization is fabricated. | Manage authorized roles/configuration through a separate, audited backend capability. |

Hiding a control in the mock UI is not an authorization check.

## Existing schemas used

### Health

```json
{"status":"healthy", "version":"0.1.0", "data_source":"simulated", "storage":"sqlite"}
```

### Observation input

`device_id`, `sequence`, `device_time_ms`, and `mq135_raw` are required. Environmental/GPS fields follow the existing Pydantic schema. The client labels MQ135 as a relative gas-sensor response only.

### Incident statuses

The backend values are `candidate`, `under_review`, `confirmed`, `dismissed`, `resolved`, and `monitoring`. The UI does not invent the requested operational values (`reported`, `inspection requested`, `action taken`, `closed`) because they do not map safely one-to-one. It displays backend status and documents the missing operational workflow in the update log.

| Requested operational label | Current safe representation |
|---|---|
| Reported | Not represented: the backend does not promote a community report into a case. |
| Needs review | `candidate` or `under_review`, shown with its precise backend value. |
| Inspection requested | Unavailable: confirmation does not prove an inspection was requested. |
| Action taken | Unavailable: the backend has no action-record field. |
| Closed | No direct mapping: `resolved` is shown exactly as `resolved`. |

## Required backend additions

See [updates-ui-backend-ui.md](updates-ui-backend-ui.md) for acceptance criteria. The highest-priority additions are authentication/authorization, source-mode status/switching, community-report listing and event fields, report/evidence links, uploads, assignments, operational case statuses, impact aggregates, rate limiting, and a live ground-station integration.
