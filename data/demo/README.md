# Dashboard CanSat-schema sample

`delhi_cansat_dashboard_sample.jsonl` contains 250 valid telemetry records: 50 records at each of five Delhi locations.

| Location | Device ID | Coordinates |
|---|---|---|
| India Gate | `burnwatch-cansat-india-gate` | 28.6129, 77.2295 |
| Anand Vihar | `burnwatch-cansat-anand-vihar` | 28.6469, 77.3160 |
| Okhla | `burnwatch-cansat-okhla` | 28.5355, 77.2740 |
| Narela | `burnwatch-cansat-narela` | 28.8520, 77.0920 |
| Bawana | `burnwatch-cansat-bawana` | 28.8030, 77.0490 |

The file uses the normal CanSat JSONL schema, valid GPS fixes, and a short elevated-response period for each device so it can exercise the map, evidence, workflow, and impact dashboards.

## Important provenance note

This is a generated **development sample**, not readings collected by a physical CanSat. It intentionally contains no `simulated` source flag because source provenance is assigned by the ingestion command, not embedded in the JSONL payload. Do not describe this file, its derived cases, or its charts as real field observations.

To load it as CanSat-provenance development data for the public dashboards, use a fresh/local database and run:

```bash
burnwatch process data/demo/delhi_cansat_dashboard_sample.jsonl --source-mode cansat
```

The UI includes only API records whose saved provenance is `source_mode: "cansat"` and `is_simulated: false`; simulated records remain available only in the administrator Operations utility for internal testing.

For real readings, replace this file with a JSONL recording made by the ground station, retain the source provenance, and follow [How to use actual CanSat readings](../../how-to.md#how-to-use-actual-cansat-readings).
