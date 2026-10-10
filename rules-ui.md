# BurnWatch UI Rules

## Engineering

- Keep the existing dependency-free static frontend unless a reviewed decision introduces a supported build toolchain.
- Use the centralized API client; do not scatter `fetch` calls through view code.
- Reuse shared panels, badges, buttons, drawers, dialogs, toasts, form fields, tables, and state renderers.
- Use semantic HTML, native controls where possible, visible focus styling, keyboard-accessible interactions, and WCAG AA contrast.
- Never embed credentials, API keys, raw serial paths, or hardware commands in browser code.

## Data integrity and scientific language

- The five public dashboards must render only `source_mode: "cansat"` records where `is_simulated` is false. Simulated records belong only in the administrator Operations utility for internal testing.
- Keep generated CanSat-schema fixtures visibly documented as development data; `cansat` source metadata alone is not proof of physical collection.
- MQ135 must be described as “Relative gas-sensor response — not a pollutant concentration or official AQI measurement.”
- Do not fabricate calibration, confidence, inspection, verification, date/time, photo, report, or connection values.
- Do not plot invalid/no-fix/missing coordinates; keep them available in a non-geographic list where the API supports it.
- Use the OpenStreetMap map interactively with visible attribution. Do not prefetch tiles, present a relative anomaly overlay as AQI/pollution concentration, or rely on shared public tiles for production-scale traffic.
- A community report is an allegation, not verification. An anomaly is a signal, not proof. Only an explicit backend confirmation represents a verified incident.

## Security boundaries

- The five dashboard routes are public in this prototype. The administrator sign-in is visual only and never authorizes backend calls.
- Hiding a control is never authorization.
- Browser code never communicates directly with serial/LoRa hardware.
- All production access control must be enforced by the backend on every request.
- Public report submission must be independently rate-limited and abuse-protected before deployment.

### Required production role matrix

| Role | Allowed capability |
|---|---|
| Public/community reporter | Submit a rate-limited report and see only an authorized acknowledgement. |
| Viewer/analyst | Read permitted maps, evidence, reports, and cases. |
| Investigator | Perform only assigned, authorized case transitions with an audit reason. |
| Operations operator | View connection status and perform explicitly authorized operational controls. |
| Administrator | Manage authorized users, roles, and configuration through audited backend functions. |

The current mock login only changes the browser's presentation. The backend must verify this matrix for every request.

## UX

- Show loading, empty, stale, disconnected, validation, permission, conflict, and server-error states honestly.
- Do not report a state update or report submission as successful until the backend acknowledges it.
- Keep exactly five primary dashboards. Operations and login remain utility views.
