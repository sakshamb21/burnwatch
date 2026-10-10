# BurnWatch — API Documentation

## Overview

BurnWatch exposes a local REST API using FastAPI. The API is the primary interface for the future frontend and external integrations.

**Base URL**: `http://127.0.0.1:8000`

**Versioning**: URL prefix `/api/v1/` (planned). Initial implementation uses root paths.

**Content-Type**: `application/json`

## Authentication

No authentication is required for local development. The API binds to `127.0.0.1` only.

For deployed use, authentication should be added at the API Gateway layer.

## Endpoints

*Endpoints will be documented as they are implemented in Phase 10.*

### Health Check

```
GET /health
```

**Response** `200 OK`:
```json
{
    "status": "healthy",
    "version": "0.1.0",
    "data_source": "simulated",
    "storage": "sqlite"
}
```

### Telemetry Status

```
GET /telemetry/status
```

Returns configured CanSat hardware serial status and parameters.

**Response** `200 OK`:
```json
{
    "configured": true,
    "status": "configured",
    "source": "COM3",
    "baud": 9600,
    "data_source_mode": "cansat"
}
```

### Submit Observation

```
POST /observations
```

**Request Body**: Canonical observation JSON.

**Response** `201 Created`:
```json
{
    "observation_id": "uuid",
    "status": "accepted",
    "quality_flags": [],
    "anomaly_detected": false
}
```

**Response** `422 Unprocessable Entity`:
```json
{
    "detail": [
        {
            "loc": ["body", "latitude"],
            "msg": "value must be between -90 and 90",
            "type": "value_error"
        }
    ]
}
```

### List Observations

```
GET /observations?limit=50&offset=0&device_id=burnwatch-cansat-01
```

**Response** `200 OK`:
```json
{
    "items": [...],
    "total": 184,
    "limit": 50,
    "offset": 0
}
```

### List Incidents

```
GET /incidents?status=candidate&limit=20&offset=0
```

**Response** `200 OK`:
```json
{
    "items": [...],
    "total": 5,
    "limit": 20,
    "offset": 0
}
```

### Get Incident

```
GET /incidents/{incident_id}
```

**Response** `200 OK`: Full incident with history.

**Response** `404 Not Found`:
```json
{
    "detail": "Incident not found"
}
```

### Review Incident

```
POST /incidents/{incident_id}/review
```

**Request Body**:
```json
{
    "reviewer": "officer_name",
    "action": "confirm",
    "notes": "Confirmed by field visit"
}
```

**Response** `200 OK`: Updated incident.

**Response** `409 Conflict`: Invalid state transition.

### Update Incident Status

```
POST /incidents/{incident_id}/status
```

**Request Body**:
```json
{
    "status": "resolved",
    "reviewer": "officer_name",
    "notes": "Cleanup completed"
}
```

**Response** `200 OK`: Updated incident.

## Error Codes

| Code | Meaning |
|---|---|
| 200 | Success |
| 201 | Created |
| 400 | Bad request |
| 404 | Not found |
| 409 | Conflict (invalid state transition) |
| 422 | Validation error |
| 500 | Internal server error |

## Idempotency

Submitting the same observation (same `device_id` + `sequence`) returns the existing record rather than creating a duplicate.

## Data Provenance

All API responses include `source_mode` to indicate whether data originated from the simulator or CanSat.
