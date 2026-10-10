# BurnWatch UI Architecture

## Current architecture

The frontend is served by FastAPI at `/` and static assets are mounted at `/static`. It is deliberately a small dependency-free single-page application because the repository already uses static browser assets and contains no JavaScript package manager, React, Vite, or component-library setup.

```text
Browser
  ├─ Public hash-router / administrator-prototype state / shared render helpers
  ├─ Five primary dashboard route views
  ├─ Central API client (relative URLs, timeout, errors)
  └─ Leaflet map client → OpenStreetMap tile service
          │
          ▼
FastAPI API
  ├─ /health
  ├─ /observations
  ├─ /incidents
  └─ /reports
          │
          ▼
SQLite local storage (current default)
```

## Route plan

The sidebar contains exactly these five primary route destinations:

| Hash route | Dashboard | Backend data used |
|---|---|---|
| `#map` | Incident Map | CanSat observations and incidents only, plus a client-side relative heat overlay and composition charts. |
| `#evidence` | Event Evidence | CanSat observations, incidents, selected incident detail. |
| `#reports` | Community Reports | `POST /reports` only. |
| `#workflow` | Investigation Workflow | CanSat incidents and audit history; mutations appear only in the administrator prototype. |
| `#impact` | Impact Report | Client-side CanSat incident aggregate and chart blocks. |

`#operations` is an administrator-only utility route. The administrator sign-in is an overlay rather than a dashboard route; neither is a primary navigation item.

## Component boundaries

`app.js` centralizes API calls in an `api` client. Rendering functions consume data from the client and use shared helpers for status badges, provenance labels, metrics, empty/loading/error states, dialogs, toast messages, accessible tables, and map markers. Components do not issue scattered ad-hoc fetches.

Shared CSS components include the application shell, navigation, panels, metric cards, status/provenance badges, buttons, tables, drawers, dialogs, field validation, chart containers, map markers, and responsive utilities.

## Data and provenance flow

1. The client reads `/health` to display configured source and connectivity.
2. It reads observations/incidents only when the backend responds successfully.
3. It retains full records for the administrator Operations utility, then filters dashboard observation and incident state to `source_mode === "cansat" && !is_simulated`.
4. It keeps reports newly acknowledged by the API in memory only because the backend lacks a reports-list endpoint.
5. It never promotes an observation or report to verified. Verification is represented only by an explicit backend `confirmed` incident status.

## Map boundary

The Incident Map uses Leaflet and the standard OpenStreetMap tile URL with visible attribution. It rejects missing, no-fix, `(0,0)`, or out-of-range coordinates from plotted markers. The translucent circles are a client-side relative signal-density overlay based on visible CanSat anomalies; they are not pollutant concentration, AQI, or an authoritative heat map. Geocoding, clustering at scale, offline maps, and production map hosting remain future integration decisions.

## Authentication and authorization boundary

Public dashboard viewing has no prototype login. The administrator interface is an in-memory visual prototype that gates Operations and UI case controls only; it cannot secure the unauthenticated backend. A future identity provider/session implementation must validate credentials server-side, attach credentials in the API client, handle `401`/`403`, enforce resource-level permissions, and protect every non-public route.

## Future live hardware boundary

The browser only displays source configuration and hardware-unavailable state. It never connects to serial hardware or sends raw device commands. A trusted backend or ground-station service must own serial/LoRa communication, decode/validate frames, apply permissions, and forward canonical observations to the pipeline/API.
