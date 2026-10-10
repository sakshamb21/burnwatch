"""BurnWatch Command-Line Interface.

Provides CLI commands for:
- Environment and configuration diagnostics (`doctor`)
- Deterministic synthetic telemetry generation (`simulate`)
- Recorded telemetry replay (`replay`)
- End-to-end pipeline processing (`process`)
- Incident inspection, listing, and human review (`incidents`)
- Development API server launcher (`api`)
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import click

from burnwatch.config.settings import DataSource, get_settings
from burnwatch.incidents.models import IncidentStatus, InvalidTransitionError
from burnwatch.incidents.service import IncidentService
from burnwatch.models.observation import SourceMode
from burnwatch.pipeline.processor import PipelineProcessor, PipelineSummary
from burnwatch.sources.cansat import CanSatLiveSource, CanSatReplaySource
from burnwatch.sources.simulator import SimulatorScenario, SimulatorSource
from burnwatch.storage.local import LocalStorage


def _setup_logging(level_name: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level_name.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )


@click.group()
@click.version_option(package_name="burnwatch")
def main() -> None:
    """BurnWatch — CanSat-Assisted Environmental Incident Investigation System."""


@main.command()
def doctor() -> None:
    """Run system diagnostics on settings, storage, and dependencies."""
    click.echo("BurnWatch System Diagnostics")
    click.echo("=" * 45)

    all_ok = True

    # 1. Configuration
    try:
        settings = get_settings()
        click.echo("[OK] Configuration:")
        for k, v in settings.summary().items():
            click.echo(f"    {k}: {v}")
    except Exception as e:
        click.echo(f"[ERROR] Configuration failed: {e}", err=True)
        all_ok = False
        sys.exit(1)

    # 2. Storage
    try:
        db = LocalStorage(settings.database_path)
        # Verify tables created
        cur = db._conn.execute("SELECT count(*) FROM sqlite_master WHERE type='table'")
        table_count = cur.fetchone()[0]
        click.echo(f"[OK] SQLite database accessible ({table_count} tables initialized)")
    except Exception as e:
        click.echo(f"[ERROR] Database check failed: {e}", err=True)
        all_ok = False

    # 3. AWS Status
    if settings.aws_configured:
        click.echo(f"[OK] AWS storage configured (region: {settings.aws_region})")
    else:
        click.echo("- AWS storage: not configured (local SQLite active)")

    # 4. CanSat Live Hardware Source
    cansat_src = settings.cansat_source
    if cansat_src:
        click.echo(
            f"[OK] CanSat serial configuration: {cansat_src} "
            f"(baud: {settings.cansat_baud})"
        )
    else:
        click.echo(
            "- CanSat live source: not configured "
            "(set BURNWATCH_CANSAT_SOURCE to enable hardware streaming)"
        )

    if all_ok:
        click.echo("\n[OK] System is healthy and ready for operation.")
    else:
        click.echo("\n[ERROR] System diagnostics reported issues.", err=True)
        sys.exit(1)


@main.command()
@click.option(
    "--scenario",
    type=click.Choice([s.value for s in SimulatorScenario]),
    default=SimulatorScenario.NORMAL.value,
    help="Simulation scenario",
)
@click.option("--count", type=int, default=200, help="Number of observations")
@click.option("--seed", type=int, default=42, help="Random seed for determinism")
@click.option(
    "--interval-ms", type=int, default=2000, help="Device time interval in ms"
)
@click.option(
    "--output",
    type=click.Path(dir_okay=False, path_type=Path),
    default=None,
    help="Path to output JSONL file (default prints to stdout)",
)
def simulate(
    scenario: str, count: int, seed: int, interval_ms: int, output: Path | None
) -> None:
    """Generate deterministic simulated observations."""
    sim = SimulatorSource(
        scenario=SimulatorScenario(scenario),
        seed=seed,
        count=count,
        interval_ms=interval_ms,
    )

    if output:
        count_written = sim.to_jsonl(output)
        click.echo(f"Wrote {count_written} observations to {output}")
    else:
        for obs in sim.observations():
            click.echo(obs.model_dump_json())


@main.command()
@click.argument("file", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--limit", type=int, default=None, help="Max records to replay")
def replay(file: Path, limit: int | None) -> None:
    """Replay recorded CanSat observations from a JSONL file."""
    source = CanSatReplaySource(file)
    count = 0
    for obs in source.observations():
        click.echo(obs.model_dump_json())
        count += 1
        if limit is not None and count >= limit:
            break
    click.echo(f"\nReplayed {count} observations from {file}", err=True)


@main.command()
@click.argument(
    "file", type=click.Path(exists=True, dir_okay=False, path_type=Path), required=False
)
@click.option(
    "--source-mode",
    type=click.Choice(["simulated", "cansat"]),
    default=None,
    help="Explicit source mode override",
)
def process(file: Path | None, source_mode: str | None) -> None:
    """Process observations through the entire BurnWatch pipeline."""
    settings = get_settings()
    _setup_logging(settings.log_level)

    db = LocalStorage(settings.database_path)
    processor = PipelineProcessor(storage=db)

    mode = (
        SourceMode(source_mode)
        if source_mode
        else (
            SourceMode.CANSAT
            if settings.data_source == DataSource.CANSAT
            else SourceMode.SIMULATED
        )
    )

    if file:
        click.echo(f"Processing observations from {file} (source={mode.value})...")
        summary = processor.process_file(file, source_mode=mode)
    else:
        click.echo(
            f"No file specified. Simulating {settings.sim_count} observations..."
        )
        sim = SimulatorSource(
            scenario=SimulatorScenario.NORMAL,
            seed=settings.sim_seed,
            count=settings.sim_count,
            interval_ms=settings.sim_interval_ms,
        )
        summary = processor.process_source(sim)

    click.echo("\n" + "=" * 45)
    click.echo("Pipeline Processing Summary")
    click.echo("=" * 45)
    click.echo(f"  Total Received:     {summary.total_received}")
    click.echo(f"  New Observations:   {summary.new_observations}")
    click.echo(f"  Duplicates Ignored: {summary.duplicates}")
    click.echo(f"  Anomalies Flagged:  {summary.anomalies_detected}")
    click.echo(f"  Incidents Created:  {summary.incidents_created}")

    if summary.quality_flag_counts:
        click.echo("\n  Quality Flags Breakdown:")
        for flag, count in summary.quality_flag_counts.items():
            click.echo(f"    - {flag}: {count}")
    click.echo("=" * 45)


@main.command()
@click.option(
    "--port",
    default=None,
    help="Serial port (e.g. COM3 or /dev/ttyUSB0). Defaults to BURNWATCH_CANSAT_SOURCE.",
)
@click.option(
    "--baud",
    default=None,
    type=int,
    help="Baud rate (e.g. 9600). Defaults to BURNWATCH_CANSAT_BAUD.",
)
@click.option(
    "--timeout",
    default=1.0,
    type=float,
    help="Serial read timeout in seconds.",
)
@click.option(
    "--limit",
    default=None,
    type=int,
    help="Max observations to ingest before stopping.",
)
@click.option(
    "--api-url",
    default=None,
    help="Optional running BurnWatch API URL to POST observations to (e.g. http://127.0.0.1:8000).",
)
def live(
    port: str | None,
    baud: int | None,
    timeout: float,
    limit: int | None,
    api_url: str | None,
) -> None:
    """Stream and ingest live telemetry from a CanSat serial ground station."""
    settings = get_settings()
    _setup_logging(settings.log_level)

    serial_port = port or settings.cansat_source
    if not serial_port:
        click.echo(
            "Error: No serial port configured. Specify --port or set "
            "BURNWATCH_CANSAT_SOURCE in .env",
            err=True,
        )
        sys.exit(1)

    baud_rate = baud or settings.cansat_baud

    click.echo(f"Opening live CanSat connection on {serial_port} ({baud_rate} baud)...")

    source = CanSatLiveSource(
        source_config=serial_port,
        baudrate=baud_rate,
        timeout=timeout,
        max_records=limit,
    )

    if api_url:
        import httpx

        target_url = f"{api_url.rstrip('/')}/observations"
        click.echo(f"Streaming observations to API: {target_url}")
        count = 0
        try:
            with httpx.Client(timeout=5.0) as client:
                for obs in source.observations():
                    resp = client.post(target_url, json=obs.model_dump(mode="json"))
                    count += 1
                    click.echo(
                        f"[{count}] seq={obs.sequence} device={obs.device_id} "
                        f"mq={obs.mq135_raw} -> HTTP {resp.status_code}"
                    )
                    if limit is not None and count >= limit:
                        break
        except ConnectionError as e:
            click.echo(f"\n[ERROR] Hardware connection failed: {e}", err=True)
            sys.exit(1)
        except Exception as e:
            click.echo(f"\n[ERROR] Streaming failed: {e}", err=True)
            sys.exit(1)
        finally:
            source.close()

        click.echo(f"\nForwarded {count} observations to API.", err=True)
        return

    db = LocalStorage(settings.database_path)
    processor = PipelineProcessor(storage=db, source_mode=SourceMode.CANSAT)
    summary = PipelineSummary()

    click.echo("Ingesting directly into local database and running anomaly pipeline...")
    click.echo("Press Ctrl+C to stop.")
    try:
        for obs, raw_payload in source.observations_with_payload():
            res = processor.process_raw(
                raw=obs, raw_payload=raw_payload, source_mode=SourceMode.CANSAT
            )
            summary.record(res)
            status_flag = "NEW" if res.is_new else "DUP"
            anomaly_flag = " [ANOMALY]" if res.observation.anomaly_detected else ""
            candidate_flag = (
                f" [CANDIDATE: {res.candidate_incident.incident_id[:8]}]"
                if res.candidate_incident
                else ""
            )
            click.echo(
                f"[{summary.total_received}] {status_flag} seq={obs.sequence} "
                f"mq={obs.mq135_raw}{anomaly_flag}{candidate_flag}"
            )
            if limit is not None and summary.total_received >= limit:
                break
    except KeyboardInterrupt:
        click.echo("\nInterrupted by operator.")
    except ConnectionError as e:
        click.echo(f"\n[ERROR] Hardware connection failed: {e}", err=True)
        sys.exit(1)
    finally:
        source.close()

    click.echo("\n" + "=" * 45)
    click.echo("Live Ingestion Summary")
    click.echo("=" * 45)
    click.echo(f"  Total Received:     {summary.total_received}")
    click.echo(f"  New Observations:   {summary.new_observations}")
    click.echo(f"  Duplicates Ignored: {summary.duplicates}")
    click.echo(f"  Anomalies Flagged:  {summary.anomalies_detected}")
    click.echo(f"  Incidents Created:  {summary.incidents_created}")


@main.group()
def incidents() -> None:
    """Manage and inspect environmental incidents."""


@incidents.command("list")
@click.option(
    "--status",
    type=click.Choice([s.value for s in IncidentStatus]),
    default=None,
    help="Filter by status",
)
@click.option("--limit", type=int, default=20, help="Max items to list")
@click.option("--offset", type=int, default=0, help="Offset for pagination")
def list_incidents(status: str | None, limit: int, offset: int) -> None:
    """List incidents matching status criteria."""
    settings = get_settings()
    db = LocalStorage(settings.database_path)
    status_enum = IncidentStatus(status) if status else None

    items, total = db.list_incidents(status=status_enum, limit=limit, offset=offset)

    click.echo(f"Incidents (Total: {total}, Showing: {len(items)}):")
    if not items:
        click.echo("  No incidents found.")
        return

    click.echo("-" * 75)
    click.echo(
        f"{'ID':<10} {'STATUS':<14} {'DEVICE':<15} {'PEAK_MQ':<9} {'SCORE':<7} {'SIMULATED'}"
    )
    click.echo("-" * 75)
    for inc in items:
        short_id = inc.incident_id[:8]
        click.echo(
            f"{short_id:<10} {inc.status.value:<14} {inc.device_id:<15} "
            f"{inc.peak_mq135:<9} {inc.peak_anomaly_score:<7.1f} {str(inc.is_simulated):<9}"
        )
    click.echo("-" * 75)


@incidents.command("show")
@click.argument("incident_id")
def show_incident(incident_id: str) -> None:
    """Show detailed incident record and complete audit history."""
    settings = get_settings()
    db = LocalStorage(settings.database_path)

    # Allow prefix match for convenience
    inc = db.get_incident(incident_id)
    if inc is None:
        # Check if user provided prefix
        all_items, _ = db.list_incidents(limit=100)
        matches = [i for i in all_items if i.incident_id.startswith(incident_id)]
        if len(matches) == 1:
            inc = matches[0]
        elif len(matches) > 1:
            click.echo(f"Error: Ambiguous incident prefix '{incident_id}'", err=True)
            sys.exit(1)
        else:
            click.echo(f"Error: Incident '{incident_id}' not found", err=True)
            sys.exit(1)

    click.echo(f"Incident: {inc.incident_id}")
    click.echo(f"  Status:       {inc.status.value}")
    click.echo(f"  Device:       {inc.device_id}")
    click.echo(
        f"  Source Mode:  {inc.source_mode.value} (is_simulated={inc.is_simulated})"
    )
    click.echo(f"  Coordinates:  ({inc.latitude}, {inc.longitude})")
    click.echo(f"  Peak MQ135:   {inc.peak_mq135}")
    click.echo(f"  Peak Score:   {inc.peak_anomaly_score}")
    click.echo(f"  Created At:   {inc.created_at.isoformat()}")
    click.echo(f"  Reviewer:     {inc.reviewer or 'None'}")
    click.echo(f"  Notes:        {inc.notes or 'None'}")
    click.echo(f"  Evidence:     {len(inc.observation_ids)} observation(s)")

    click.echo("\nAudit History:")
    if not inc.history:
        click.echo("  (No transitions recorded)")
    else:
        for entry in inc.history:
            ts = entry.timestamp.strftime("%Y-%m-%d %H:%M:%S UTC")
            click.echo(
                f"  [{ts}] {entry.from_status.value} -> {entry.to_status.value} "
                f"by {entry.actor}: {entry.notes}"
            )


@incidents.command("review")
@click.argument("incident_id")
@click.option(
    "--action",
    type=click.Choice(["under_review", "confirm", "dismiss"]),
    required=True,
    help="Review action",
)
@click.option("--reviewer", required=True, help="Reviewer name / officer ID")
@click.option("--notes", required=True, help="Review justification notes")
def review_incident(incident_id: str, action: str, reviewer: str, notes: str) -> None:
    """Perform human review action on an incident."""
    settings = get_settings()
    db = LocalStorage(settings.database_path)
    service = IncidentService(storage=db)

    # Check prefix match
    inc = db.get_incident(incident_id)
    if inc is None:
        all_items, _ = db.list_incidents(limit=100)
        matches = [i for i in all_items if i.incident_id.startswith(incident_id)]
        if len(matches) == 1:
            incident_id = matches[0].incident_id
        else:
            click.echo(f"Error: Incident '{incident_id}' not found", err=True)
            sys.exit(1)

    try:
        updated = service.review_incident(
            incident_id=incident_id,
            action=action,
            reviewer=reviewer,
            notes=notes,
        )
        click.echo(
            f"[OK] Incident {updated.incident_id[:8]} updated to {updated.status.value}."
        )
    except InvalidTransitionError as e:
        click.echo(f"[ERROR] Transition rejected: {e}", err=True)
        sys.exit(1)
    except Exception as e:
        click.echo(f"[ERROR] Review failed: {e}", err=True)
        sys.exit(1)


@main.command()
@click.option("--host", default=None, help="Host to bind to")
@click.option("--port", type=int, default=None, help="Port to listen on")
@click.option("--reload", is_flag=True, default=False, help="Enable auto-reload")
def api(host: str | None, port: int | None, reload: bool) -> None:
    """Launch the BurnWatch FastAPI server."""
    import uvicorn

    settings = get_settings()
    bind_host = host or settings.api_host
    bind_port = port or settings.api_port

    click.echo(f"Starting BurnWatch API on {bind_host}:{bind_port}...")
    uvicorn.run(
        "burnwatch.api.app:app",
        host=bind_host,
        port=bind_port,
        reload=reload,
    )


if __name__ == "__main__":
    main()
