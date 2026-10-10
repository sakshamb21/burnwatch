"""Comprehensive tests for the CanSat live serial connection adapter."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner
from pydantic import ValidationError
from starlette.testclient import TestClient

from burnwatch.api.app import create_app
from burnwatch.cli import main
from burnwatch.models.observation import SourceMode
from burnwatch.pipeline.processor import PipelineProcessor
from burnwatch.sources.cansat import CanSatLiveSource
from burnwatch.sources.serial import (
    ConnectionState,
    MockSerialPort,
    SerialConfig,
    SerialConnection,
    SerialManager,
    list_serial_ports,
    normalize_telemetry_dict,
)
from burnwatch.storage.local import LocalStorage


class TestSerialConfig:
    """Tests for SerialConfig parsing and validation."""

    def test_parse_windows_com_port(self) -> None:
        cfg = SerialConfig.from_connection_string("COM3")
        assert cfg.port == "COM3"
        assert cfg.baudrate == 9600

    def test_parse_windows_com_port_with_baud(self) -> None:
        cfg = SerialConfig.from_connection_string("COM4:115200")
        assert cfg.port == "COM4"
        assert cfg.baudrate == 115200

    def test_parse_unix_port(self) -> None:
        cfg = SerialConfig.from_connection_string("/dev/ttyUSB0")
        assert cfg.port == "/dev/ttyUSB0"
        assert cfg.baudrate == 9600

    def test_parse_unix_port_with_baud(self) -> None:
        cfg = SerialConfig.from_connection_string("/dev/ttyUSB0:57600")
        assert cfg.port == "/dev/ttyUSB0"
        assert cfg.baudrate == 57600

    def test_parse_serial_url_prefix(self) -> None:
        cfg = SerialConfig.from_connection_string("serial:///dev/ttyACM0:115200")
        assert cfg.port == "/dev/ttyACM0"
        assert cfg.baudrate == 115200

    def test_empty_string_raises(self) -> None:
        with pytest.raises(ValueError, match="cannot be empty"):
            SerialConfig.from_connection_string("   ")

    def test_unsupported_protocol_raises(self) -> None:
        with pytest.raises(ValueError, match="Unsupported connection protocol"):
            SerialConfig.from_connection_string("tcp://192.168.1.50:9000")


class TestNormalizeTelemetryDict:
    """Tests for firmware telemetry field translation."""

    def test_canonical_dict_preserved(self, canonical_obs: dict) -> None:
        obs = normalize_telemetry_dict(canonical_obs)
        assert obs.device_id == canonical_obs["device_id"]
        assert obs.sequence == canonical_obs["sequence"]
        assert obs.mq135_raw == canonical_obs["mq135_raw"]
        assert obs.temperature_c == canonical_obs["temperature_c"]
        assert obs.humidity_pct == canonical_obs["humidity_pct"]

    def test_translates_firmware_aliases(self) -> None:
        firmware_payload = {
            "id": "esp32-node-7",
            "seq": 42,
            "time_ms": 84000,
            "gas": 380,
            "temp": 30.5,
            "hum": 52.0,
            "press": 1008.2,
            "lat": 28.61,
            "lon": 77.23,
            "fix": 1,
            "sats": 8,
        }
        obs = normalize_telemetry_dict(firmware_payload)
        assert obs.device_id == "esp32-node-7"
        assert obs.sequence == 42
        assert obs.device_time_ms == 84000
        assert obs.mq135_raw == 380
        assert obs.temperature_c == 30.5
        assert obs.humidity_pct == 52.0
        assert obs.pressure_hpa == 1008.2
        assert obs.latitude == 28.61
        assert obs.longitude == 77.23
        assert obs.gps_fix is True
        assert obs.satellites == 8

    def test_ignores_unknown_extra_fields(self, canonical_obs: dict) -> None:
        with_extra = {
            **canonical_obs,
            "battery_mv": 3720,
            "rssi": -65,
            "snr": 9.2,
        }
        obs = normalize_telemetry_dict(with_extra)
        assert obs.device_id == canonical_obs["device_id"]
        assert obs.sequence == canonical_obs["sequence"]

    def test_invalid_range_raises_validation_error(self, canonical_obs: dict) -> None:
        bad = {**canonical_obs, "mq135_raw": 9999}
        with pytest.raises(ValidationError):
            normalize_telemetry_dict(bad)


class TestSerialConnection:
    """Tests for low-level SerialConnection behavior."""

    def test_successful_read_stream(self, canonical_obs_json: str) -> None:
        lines = [canonical_obs_json, canonical_obs_json]
        cfg = SerialConfig(port="MOCK_PORT", baudrate=9600)
        conn = SerialConnection(
            config=cfg,
            serial_factory=lambda port, baud, timeout: MockSerialPort(
                lines=lines, auto_close_on_eof=False
            ),
        )

        read_lines = list(conn.stream_lines(limit=2))
        assert len(read_lines) == 2
        assert read_lines[0] == canonical_obs_json
        assert conn.packets_received == 2
        assert conn.bytes_received > 0
        assert conn.last_packet_time is not None
        assert conn.is_connected is True

    def test_timeout_returns_none(self) -> None:
        cfg = SerialConfig(port="MOCK_PORT", baudrate=9600)
        conn = SerialConnection(
            config=cfg,
            serial_factory=lambda port, baud, timeout: MockSerialPort(lines=[]),
        )
        conn.connect()
        assert conn.read_line() is None
        conn.close()
        assert conn.is_connected is False

    def test_context_manager_lifecycle(self, canonical_obs_json: str) -> None:
        cfg = SerialConfig(port="MOCK_PORT", baudrate=9600)
        conn = SerialConnection(
            config=cfg,
            serial_factory=lambda port, baud, timeout: MockSerialPort(lines=[canonical_obs_json]),
        )
        with conn:
            assert conn.is_connected is True
            line = conn.read_line()
            assert line == canonical_obs_json
        assert conn.is_connected is False

    def test_reconnect_on_transient_error(self, canonical_obs_json: str) -> None:
        cfg = SerialConfig(
            port="MOCK_PORT",
            baudrate=9600,
            reconnect=True,
            max_retries=2,
            retry_delay_s=0.001,
        )
        calls = 0

        def factory(port, baud, timeout):
            nonlocal calls
            calls += 1
            if calls == 1:
                return MockSerialPort(
                    lines=[canonical_obs_json],
                    raise_on_read=OSError("Transient UART buffer error"),
                )
            return MockSerialPort(lines=[canonical_obs_json])

        delays_slept: list[float] = []

        conn = SerialConnection(
            config=cfg,
            serial_factory=factory,
            sleep_fn=delays_slept.append,
        )
        conn.connect()
        # First read triggers reconnect
        line = conn.read_line()
        assert line is None  # Handled transient error
        assert conn.state == ConnectionState.CONNECTED
        assert len(delays_slept) == 1

        # Second read returns the line after reconnect
        line2 = conn.read_line()
        assert line2 == canonical_obs_json

    def test_reconnect_exhausted_raises(self) -> None:
        cfg = SerialConfig(
            port="MOCK_PORT",
            baudrate=9600,
            reconnect=True,
            max_retries=2,
            retry_delay_s=0.001,
        )

        def failing_factory(port, baud, timeout):
            raise OSError("Hardware disconnected completely")

        conn = SerialConnection(
            config=cfg,
            serial_factory=failing_factory,
            sleep_fn=lambda _: None,
        )
        with pytest.raises(ConnectionError, match="Failed to connect to serial port"):
            conn.connect()

    def test_health_dictionary(self) -> None:
        cfg = SerialConfig(port="COM7", baudrate=115200)
        conn = SerialConnection(
            config=cfg,
            serial_factory=lambda port, baud, timeout: MockSerialPort(lines=[]),
        )
        conn.connect()
        h = conn.health()
        assert h["port"] == "COM7"
        assert h["baudrate"] == 115200
        assert h["is_connected"] is True
        assert h["state"] == "connected"
        assert h["packets_received"] == 0


class TestCanSatLiveSourceAdapter:
    """Tests for CanSatLiveSource adapter end-to-end functionality."""

    def test_unconfigured_source_raises(self) -> None:
        source = CanSatLiveSource()
        assert source.source_mode == SourceMode.CANSAT
        assert source.is_configured is False
        with pytest.raises(ConnectionError, match="not configured"):
            list(source.observations())

    def test_unsupported_protocol_raises(self) -> None:
        source = CanSatLiveSource("tcp://groundstation:9000")
        assert source.is_configured is True
        with pytest.raises(ConnectionError, match="not implemented"):
            list(source.observations())

    def test_reads_mock_serial_telemetry(self, canonical_obs: dict) -> None:
        line1 = json.dumps(canonical_obs)
        line2 = json.dumps({**canonical_obs, "sequence": 185, "mq135_raw": 510})
        lines = [line1, line2]

        source = CanSatLiveSource(
            source_config="COM3:9600",
            serial_factory=lambda port, baud, timeout: MockSerialPort(lines=lines),
        )
        obs_list = list(source.observations())
        assert len(obs_list) == 2
        assert obs_list[0].sequence == 184
        assert obs_list[1].sequence == 185
        assert obs_list[1].mq135_raw == 510

        h = source.health()
        assert h["configured"] is True
        assert h["packets_valid"] == 2
        assert h["packets_corrupt"] == 0

    def test_observations_with_payload_preserves_raw_string(self, canonical_obs_json: str) -> None:
        source = CanSatLiveSource(
            source_config="/dev/ttyUSB0",
            serial_factory=lambda port, baud, timeout: MockSerialPort(lines=[canonical_obs_json]),
        )
        results = list(source.observations_with_payload())
        assert len(results) == 1
        obs, raw_payload = results[0]
        assert obs.device_id == "burnwatch-cansat-01"
        assert raw_payload == canonical_obs_json

    def test_skips_corrupt_frames_and_non_json_lines(self, canonical_obs: dict) -> None:
        lines = [
            "[INFO] Booting CanSat Ground Station v1.2",
            "--- Starting Telemetry Stream ---",
            "{corrupt_json: true}",
            json.dumps(canonical_obs),
            "noise",
            json.dumps({**canonical_obs, "sequence": 185}),
        ]
        source = CanSatLiveSource(
            source_config="COM5",
            serial_factory=lambda port, baud, timeout: MockSerialPort(lines=lines),
        )
        obs_list = list(source.observations())
        assert len(obs_list) == 2
        assert obs_list[0].sequence == 184
        assert obs_list[1].sequence == 185

        h = source.health()
        assert h["packets_valid"] == 2
        assert h["packets_corrupt"] >= 1  # Malformed JSON counted

    def test_pipeline_processor_integration_with_live_source(
        self, tmp_path: Path, canonical_obs: dict
    ) -> None:
        db = LocalStorage(tmp_path / "test_live.db")
        processor = PipelineProcessor(storage=db, source_mode=SourceMode.CANSAT)

        # 3 observations, one anomaly
        obs1 = {**canonical_obs, "sequence": 1, "mq135_raw": 400}
        obs2 = {**canonical_obs, "sequence": 2, "mq135_raw": 405}
        obs3 = {**canonical_obs, "sequence": 3, "mq135_raw": 850}

        lines = [json.dumps(obs1), json.dumps(obs2), json.dumps(obs3)]
        source = CanSatLiveSource(
            source_config="COM3:9600",
            serial_factory=lambda port, baud, timeout: MockSerialPort(lines=lines),
        )

        summary = processor.process_source(source)
        assert summary.total_received == 3
        assert summary.new_observations == 3

        # Verify raw_payload was stored for audit provenance
        stored, _ = db.list_observations(limit=10)
        assert len(stored) == 3
        assert stored[0].source_mode == SourceMode.CANSAT
        assert stored[0].is_simulated is False
        assert stored[0].raw_payload is not None
        assert "burnwatch-cansat-01" in stored[0].raw_payload


class TestSerialCLI:
    """Tests for CLI live streaming command and doctor checks."""

    def test_doctor_reports_cansat_serial(self, monkeypatch: pytest.MonkeyPatch) -> None:
        runner = CliRunner()
        monkeypatch.setenv("BURNWATCH_CANSAT_SOURCE", "COM3")
        monkeypatch.setenv("BURNWATCH_CANSAT_BAUD", "115200")

        result = runner.invoke(main, ["doctor"])
        assert result.exit_code == 0
        assert "CanSat serial configuration: COM3" in result.output
        assert "115200" in result.output

    def test_live_command_fails_without_port(self, monkeypatch: pytest.MonkeyPatch) -> None:
        runner = CliRunner()
        monkeypatch.delenv("BURNWATCH_CANSAT_SOURCE", raising=False)

        result = runner.invoke(main, ["live"])
        assert result.exit_code != 0
        assert "No serial port configured" in result.output


class TestTelemetryAPI:
    """Tests for API telemetry status endpoints."""

    def test_telemetry_status_unconfigured(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("BURNWATCH_CANSAT_SOURCE", raising=False)
        app = create_app()
        client = TestClient(app)

        resp = client.get("/telemetry/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["configured"] is False
        assert data["status"] == "unconfigured"

    def test_telemetry_status_configured(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("BURNWATCH_CANSAT_SOURCE", "COM4")
        monkeypatch.setenv("BURNWATCH_CANSAT_BAUD", "115200")
        app = create_app()
        client = TestClient(app)

        resp = client.get("/telemetry/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["configured"] is True
        assert data["status"] == "configured"
        assert data["source"] == "COM4"
        assert data["baud"] == 115200

        # Also verify health endpoint includes telemetry info
        health_resp = client.get("/health")
        assert health_resp.status_code == 200
        h_data = health_resp.json()
        assert "telemetry" in h_data
        assert h_data["telemetry"]["configured"] is True
        assert h_data["telemetry"]["source"] == "COM4"


class TestListSerialPorts:
    """Tests for system detectable serial ports."""

    def test_list_serial_ports_returns_list(self) -> None:
        ports = list_serial_ports()
        assert isinstance(ports, list)

    def test_list_serial_ports_mocked(self, monkeypatch: pytest.MonkeyPatch) -> None:
        class DummyPort:
            device = "COM5"
            description = "USB-SERIAL CH340 (COM5)"
            hwid = "USB VID:PID=1A86:7523"
            manufacturer = "wch.cn"

        import serial.tools.list_ports
        monkeypatch.setattr(serial.tools.list_ports, "comports", lambda: [DummyPort()])

        ports = list_serial_ports()
        assert len(ports) == 1
        assert ports[0]["port"] == "COM5"
        assert ports[0]["description"] == "USB-SERIAL CH340 (COM5)"
        assert ports[0]["manufacturer"] == "wch.cn"


class TestSerialManager:
    """Tests for SerialManager lifecycle and background telemetry ingestion."""

    def test_manager_connect_and_stream(self) -> None:
        telemetry_line = json.dumps({
            "device_id": "test-cansat-live",
            "sequence": 1,
            "device_time_ms": 1000,
            "mq135_raw": 420,
            "temperature_c": 28.5,
            "humidity_pct": 50.0,
            "pressure_hpa": 1013.25,
            "latitude": 28.6,
            "longitude": 77.2,
            "gps_fix": True,
            "satellites": 7,
        })
        received: list[dict] = []

        mock_port = MockSerialPort(lines=[telemetry_line], auto_close_on_eof=False)
        manager = SerialManager(
            on_observation=lambda obs: received.append(obs.model_dump()),
            serial_factory=lambda *a, **kw: mock_port,
        )

        status = manager.connect("COM5", 9600)
        assert status["is_connected"] is True
        assert status["port"] == "COM5"
        assert manager.is_connected is True

        # Wait briefly for background thread to read frame
        import time
        time.sleep(0.3)
        assert len(received) >= 1
        assert received[0]["device_id"] == "test-cansat-live"

        disc_status = manager.disconnect()
        assert disc_status["is_connected"] is False
        assert manager.is_connected is False

    def test_manager_disconnect_idempotent(self) -> None:
        manager = SerialManager()
        assert manager.is_connected is False
        status = manager.disconnect()
        assert status["is_connected"] is False


class TestSerialRestEndpoints:
    """Tests for REST endpoints: /serial/ports, /serial/status, /serial/connect, /serial/disconnect."""

    def test_get_serial_ports(self) -> None:
        app = create_app()
        client = TestClient(app)
        resp = client.get("/serial/ports")
        assert resp.status_code == 200
        data = resp.json()
        assert "ports" in data
        assert isinstance(data["ports"], list)

    def test_get_serial_status_initially_disconnected(self) -> None:
        app = create_app()
        client = TestClient(app)
        resp = client.get("/serial/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["is_connected"] is False
        assert data["state"] == "disconnected"

    def test_connect_and_disconnect_serial(self) -> None:
        mock_port = MockSerialPort(lines=[], auto_close_on_eof=False)
        manager = SerialManager(serial_factory=lambda *a, **kw: mock_port)
        app = create_app(serial_manager=manager)
        client = TestClient(app)

        connect_resp = client.post("/serial/connect", json={"port": "COM6", "baudrate": 115200})
        assert connect_resp.status_code == 200
        c_data = connect_resp.json()
        assert c_data["is_connected"] is True
        assert c_data["port"] == "COM6"

        status_resp = client.get("/serial/status")
        assert status_resp.status_code == 200
        assert status_resp.json()["is_connected"] is True

        disconnect_resp = client.post("/serial/disconnect")
        assert disconnect_resp.status_code == 200
        assert disconnect_resp.json()["is_connected"] is False

