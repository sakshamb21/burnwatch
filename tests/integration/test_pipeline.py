"""Integration tests for BurnWatch PipelineProcessor and CLI."""

from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from burnwatch.cli import main
from burnwatch.incidents.models import IncidentStatus
from burnwatch.models.observation import SourceMode
from burnwatch.pipeline.processor import PipelineProcessor
from burnwatch.sources.simulator import SimulatorScenario, SimulatorSource
from burnwatch.storage.local import LocalStorage


class TestPipelineProcessor:
    """End-to-end tests for the observation processing pipeline."""

    def test_pipeline_normal_stream(self) -> None:
        db = LocalStorage(":memory:")
        processor = PipelineProcessor(storage=db)

        sim = SimulatorSource(
            scenario=SimulatorScenario.NORMAL,
            seed=42,
            count=50,
            interval_ms=1000,
        )
        summary = processor.process_source(sim)

        assert summary.total_received == 50
        assert summary.new_observations == 50
        assert summary.duplicates == 0
        assert summary.incidents_created == 0

        # Verify observations exist in DB
        items, total = db.list_observations()
        assert total == 50

    def test_pipeline_sustained_anomaly_creates_incident(self) -> None:
        db = LocalStorage(":memory:")
        processor = PipelineProcessor(storage=db, source_mode=SourceMode.SIMULATED)

        sim = SimulatorSource(
            scenario=SimulatorScenario.SUSTAINED_ANOMALY,
            seed=42,
            count=100,
            interval_ms=1000,
        )
        summary = processor.process_source(sim)

        assert summary.total_received == 100
        assert summary.anomalies_detected > 0
        assert summary.incidents_created >= 1

        # Check incident in storage
        incidents, total_inc = db.list_incidents()
        assert total_inc >= 1
        assert incidents[0].status == IncidentStatus.CANDIDATE
        assert incidents[0].is_simulated is True

    def test_pipeline_duplicate_idempotency(self) -> None:
        db = LocalStorage(":memory:")
        processor = PipelineProcessor(storage=db)

        sim = SimulatorSource(
            scenario=SimulatorScenario.DUPLICATE_PACKET,
            seed=42,
            count=50,
            interval_ms=1000,
        )
        summary = processor.process_source(sim)

        # Simulator duplicate_packet scenario generates intentionally duplicate records
        assert summary.duplicates >= 2
        assert summary.total_received > summary.new_observations

    def test_pipeline_process_jsonl_file(
        self, tmp_path: Path, canonical_obs: dict
    ) -> None:
        file_path = tmp_path / "stream.jsonl"
        lines = []
        for i in range(1, 20):
            lines.append(
                json.dumps({**canonical_obs, "sequence": i, "device_time_ms": i * 1000})
            )
        file_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

        db = LocalStorage(":memory:")
        processor = PipelineProcessor(storage=db)
        summary = processor.process_file(file_path, source_mode=SourceMode.CANSAT)

        assert summary.total_received == 19
        assert summary.new_observations == 19


class TestCLICommands:
    """Tests for Click CLI commands, output formatting, and exit codes."""

    def test_cli_help(self) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["--help"])
        assert result.exit_code == 0
        assert "BurnWatch" in result.output
        assert "doctor" in result.output
        assert "simulate" in result.output
        assert "process" in result.output

    def test_cli_doctor(self) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["doctor"])
        assert result.exit_code == 0
        assert "BurnWatch System Diagnostics" in result.output
        assert "SQLite database accessible" in result.output

    def test_cli_simulate_stdout(self) -> None:
        runner = CliRunner()
        result = runner.invoke(
            main, ["simulate", "--scenario", "normal", "--count", "5", "--seed", "42"]
        )
        assert result.exit_code == 0
        lines = [ln for ln in result.output.strip().splitlines() if ln.startswith("{")]
        assert len(lines) == 5

    def test_cli_simulate_output_file(self, tmp_path: Path) -> None:
        out_file = tmp_path / "sim.jsonl"
        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "simulate",
                "--scenario",
                "normal",
                "--count",
                "10",
                "--output",
                str(out_file),
            ],
        )
        assert result.exit_code == 0
        assert out_file.exists()
        assert len(out_file.read_text(encoding="utf-8").strip().splitlines()) == 10

    def test_cli_process_and_incidents_list(self, tmp_path: Path) -> None:
        db_path = tmp_path / "cli_test.db"
        sim_file = tmp_path / "sim.jsonl"

        runner = CliRunner(env={"BURNWATCH_DATABASE_PATH": str(db_path)})

        # 1. Generate simulation file with sustained anomaly
        runner.invoke(
            main,
            [
                "simulate",
                "--scenario",
                "sustained_anomaly",
                "--count",
                "80",
                "--output",
                str(sim_file),
            ],
        )

        # 2. Process file
        proc_result = runner.invoke(main, ["process", str(sim_file)])
        assert proc_result.exit_code == 0
        assert "Pipeline Processing Summary" in proc_result.output

        # 3. List incidents
        list_result = runner.invoke(main, ["incidents", "list"])
        assert list_result.exit_code == 0
        assert "Incidents" in list_result.output

    def test_cli_replay_nonexistent_file_exits_nonzero(self) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["replay", "nonexistent_file_xyz.jsonl"])
        assert result.exit_code != 0
