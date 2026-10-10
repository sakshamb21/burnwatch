"""CanSat observation adapter.

Supports two modes:
1. Replay: Read observations from a recorded JSONL file.
2. Live: Interface for the ground station to deliver JSON observations.

The adapter uses the same ObservationSource interface as the simulator,
so the downstream pipeline is source-agnostic.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from burnwatch.ingestion.parser import parse_jsonl_file
from burnwatch.models.observation import RawObservation, SourceMode
from burnwatch.sources.base import ObservationSource
from burnwatch.sources.serial import (
    ConnectionState,
    SerialConfig,
    SerialConnection,
    normalize_telemetry_dict,
)

logger = logging.getLogger(__name__)


class CanSatReplaySource(ObservationSource):
    """Replay recorded CanSat observations from a JSONL file.

    This adapter reads a file of recorded JSON observations (one per line)
    and yields them through the standard source interface. Malformed lines
    are logged and skipped.

    Args:
        file_path: Path to the JSONL file with recorded observations.
    """

    def __init__(self, file_path: Path) -> None:
        self.file_path = file_path
        if not self.file_path.exists():
            raise FileNotFoundError(f"CanSat replay file not found: {self.file_path}")

    @property
    def source_mode(self) -> SourceMode:
        return SourceMode.CANSAT

    def observations(self) -> Iterator[RawObservation]:
        """Yield observations from the replay file.

        Malformed lines are logged and skipped. The overall replay
        continues even if individual records are invalid.
        """
        valid_count = 0
        error_count = 0

        for result in parse_jsonl_file(self.file_path):
            if result.is_valid:
                yield result.observation
                valid_count += 1
            else:
                error_count += 1
                logger.warning(
                    "Skipping invalid record in replay: %s",
                    result.error,
                )

        logger.info(
            "Replay complete: %d valid, %d errors from %s",
            valid_count,
            error_count,
            self.file_path,
        )


class CanSatLiveSource(ObservationSource):
    """Live observation source adapter for physical CanSat hardware.

    Connects to a serial port (USB-to-UART / LoRa ground-station receiver),
    translates firmware telemetry field names into the canonical schema,
    preserves raw payloads for audit provenance, and exposes connection health tracking.
    """

    def __init__(
        self,
        source_config: str = "",
        baudrate: int | None = None,
        timeout: float = 1.0,
        reconnect: bool = True,
        max_retries: int = 3,
        retry_delay_s: float = 1.0,
        backoff_factor: float = 2.0,
        serial_factory: Any = None,
        connection: SerialConnection | None = None,
        max_records: int | None = None,
    ) -> None:
        """Initialize the live serial source adapter.

        Args:
            source_config: Serial connection string (e.g. 'COM3', 'COM3:9600', '/dev/ttyUSB0')
            baudrate: Optional baudrate override (default 9600)
            timeout: Serial read timeout in seconds
            reconnect: Enable exponential backoff reconnection on disconnection
            max_retries: Reconnect attempt limit
            retry_delay_s: Initial delay between retries
            backoff_factor: Exponential backoff factor
            serial_factory: Optional serial transport factory for testing/dependency injection
            connection: Optional pre-configured SerialConnection instance
            max_records: Optional maximum records to yield before stopping
        """
        self.source_config = source_config.strip()
        self.max_records = max_records
        self._unsupported_protocol: str | None = None
        self._connection: SerialConnection | None = connection

        if self._connection is None and self.source_config:
            # Check for non-serial protocol prefixes (e.g. tcp://, socket://)
            if "://" in self.source_config and not self.source_config.startswith("serial://"):
                self._unsupported_protocol = self.source_config
            else:
                try:
                    cfg = SerialConfig.from_connection_string(
                        self.source_config,
                        default_baud=baudrate or 9600,
                        timeout=timeout,
                        reconnect=reconnect,
                        max_retries=max_retries,
                        retry_delay_s=retry_delay_s,
                        backoff_factor=backoff_factor,
                    )
                    self._connection = SerialConnection(
                        config=cfg, serial_factory=serial_factory
                    )
                except ValueError:
                    self._unsupported_protocol = self.source_config

    @property
    def source_mode(self) -> SourceMode:
        return SourceMode.CANSAT

    @property
    def is_configured(self) -> bool:
        return bool(self._connection is not None or self._unsupported_protocol)

    @property
    def connection(self) -> SerialConnection | None:
        return self._connection

    def parse_frame(self, line: str) -> RawObservation | None:
        """Parse, normalize, and validate a single serial telemetry line."""
        stripped = line.strip()
        if not stripped:
            return None

        # Ignore debug output or boot messages that are not JSON objects
        if not (stripped.startswith("{") and stripped.endswith("}")):
            logger.debug("Skipping non-JSON serial line: %s", stripped[:100])
            return None

        try:
            data = json.loads(stripped)
        except json.JSONDecodeError as e:
            if self._connection:
                self._connection.packets_corrupt += 1
            logger.warning("Corrupt JSON frame received from serial: %s (%s)", stripped[:100], e)
            return None

        if not isinstance(data, dict):
            if self._connection:
                self._connection.packets_corrupt += 1
            logger.warning("Serial frame is not a JSON object: %s", type(data).__name__)
            return None

        try:
            obs = normalize_telemetry_dict(data)
            if self._connection:
                self._connection.packets_valid += 1
            return obs
        except Exception as e:
            if self._connection:
                self._connection.packets_corrupt += 1
            logger.warning("Telemetry validation failed for frame: %s (%s)", stripped[:100], e)
            return None

    def observations_with_payload(self) -> Iterator[tuple[RawObservation, str]]:
        """Yield tuples of (RawObservation, raw_payload_json) from the live stream.

        Preserves the raw received payload for audit provenance.
        """
        if self._unsupported_protocol:
            raise ConnectionError(
                f"Live connection to '{self.source_config}' not implemented. "
                "Use CanSatReplaySource with recorded JSONL data for development."
            )

        if not self.is_configured or self._connection is None:
            raise ConnectionError(
                "CanSat live source not configured. "
                "Set BURNWATCH_CANSAT_SOURCE to a replay file path "
                "or connection string."
            )

        if not self._connection.is_connected:
            self._connection.connect()

        count = 0
        for line in self._connection.stream_lines(limit=self.max_records):
            obs = self.parse_frame(line)
            if obs is not None:
                yield obs, line
                count += 1
                if self.max_records is not None and count >= self.max_records:
                    break

    def observations(self) -> Iterator[RawObservation]:
        """Yield validated observations from the live ground station."""
        for obs, _ in self.observations_with_payload():
            yield obs

    def health(self) -> dict[str, Any]:
        """Return connection health, statistics, and freshness."""
        if self._connection is not None:
            info = self._connection.health()
            info["configured"] = True
            info["source"] = self.source_config
            return info

        return {
            "configured": False,
            "source": self.source_config or None,
            "state": ConnectionState.DISCONNECTED.value,
            "is_connected": False,
            "packets_received": 0,
            "packets_valid": 0,
            "packets_corrupt": 0,
            "last_packet_time": None,
            "last_error": None,
        }

    def close(self) -> None:
        """Close the underlying serial connection."""
        if self._connection is not None:
            self._connection.close()

    def __enter__(self) -> CanSatLiveSource:
        if self._connection and not self._connection.is_connected:
            self._connection.connect()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()
