# BurnWatch UI Testing

## Automated checks

Run the existing backend tests and static checks:

```bash
pytest
ruff check src tests
node --check src/burnwatch/api/static/app.js
```

The frontend deliberately has no external JS test runner or build system. Integration coverage verifies the root page and static asset are served. Add a browser test framework only when a maintained frontend build/test toolchain is introduced.

## Manual acceptance checks

1. Start `burnwatch api`; load the UI at desktop and narrow mobile widths.
2. Verify the primary sidebar has exactly Incident Map, Event Evidence, Community Reports, Investigation Workflow, and Impact Report.
3. Confirm all five dashboards load before sign-in. Use the sidebar Administrator sign-in action, verify its “prototype only” warning and that Operations/case controls appear, then log out and confirm in-memory session state clears while dashboards remain accessible.
4. Stop the API and verify an honest disconnected/error state with no silent demo data.
5. In simulated mode, use administrator Operations to create test telemetry. Confirm it appears only in Operations and is absent from all five dashboards; confirmation must fail for a simulated incident.
6. Load `data/demo/delhi_cansat_dashboard_sample.jsonl` using `--source-mode cansat`; confirm the dashboards show five Delhi device locations, the OpenStreetMap map, relative heat overlay, donut/bar composition charts, and Impact Report chart blocks. Confirm documentation labels this fixture as generated development data rather than field collection.
7. In CanSat mode, confirm test generation is unavailable, source status says configured-not-connected, and no fake hardware connection is displayed.
8. Submit a valid community report; confirm success only after an API response. Check required field errors. Confirm photo/date-time gaps are clearly unavailable.
9. Verify invalid/no-fix coordinates do not receive a map marker.
10. Inspect Event Evidence and verify the required MQ135 caveat and a text/table equivalent of visual data.
11. Attempt a valid and invalid incident transition as the administrator prototype. Confirm server success/error governs the displayed state.
12. Verify Impact Report keeps candidate and confirmed counts separate, is card/block based, and labels unavailable metrics.
13. Toggle light mode, collapse/expand the desktop sidebar, and use the mobile drawer at narrow widths.

## Accessibility checks

- Navigate every visible control using keyboard only.
- Check visible focus styles, skip link, landmarks, semantic headings, table headers, form labels, error messages, dialogs/drawers, and close controls.
- Check active/inactive states are communicated with text/shape as well as color.
- Use browser zoom at 200% and narrow width; no essential control should become inaccessible.
- Inspect contrast with a WCAG AA contrast checker before release.

## Security and permission checks

UI role guards are not security tests. Before deployment, backend tests must prove missing/expired credentials, `401`/`403`, viewer write attempts, resource-level access, unauthorized operational/source controls, public-report rate limits, malformed/oversized inputs, audit logging, and forbidden serial access. These are production blockers until implemented.
