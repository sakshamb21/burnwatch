"""Serial connection management and telemetry framing for CanSat hardware.

Provides robust serial port communication with:
- Configurable port, baudrate, timeouts, and reconnection policies.
- Frame buffering and safe UTF-8 decoding.
- Firmware field alias translation to canonical observation schema.
- Telemetry statistics (packets received, valid, corrupt, last timestamp).
- Dependency injection / mock support for deterministic testing.
"""

from __future__ import annotations

import logging
import sys
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from burnwatch.models.observation import RawObservation

logger = logging.getLogger(__name__)

# Known field aliases used across diverse CanSat / Arduino / ESP32 firmwares.
# Translates firmware field names to canonical RawObservation schema without inventing data.
FIELD_ALIASES: dict[str, str] = {
    "id": "device_id",
    "device": "device_id",
    "node_id": "device_id",
    "dev_id": "device_id",
    "seq": "sequence",
    "packet_id": "sequence",
    "pkt": "sequence",
    "time_ms": "device_time_ms",
    "uptime_ms": "device_time_ms",
    "millis": "device_time_ms",
    "mq135": "mq135_raw",
    "gas": "mq135_raw",
    "gas_raw": "mq135_raw",
    "raw_mq135": "mq135_raw",
    "temp": "temperature_c",
    "temp_c": "temperature_c",
    "temperature": "temperature_c",
    "hum": "humidity_pct",
    "hum_pct": "humidity_pct",
    "humidity": "humidity_pct",
    "press": "pressure_hpa",
    "press_hpa": "pressure_hpa",
    "pressure": "pressure_hpa",
    "lat": "latitude",
    "lon": "longitude",
    "lng": "longitude",
    "fix": "gps_fix",
    "sats": "satellites",
    "sat_count": "satellites",
}

CANONICAL_FIELDS: set[str] = {
    "device_id",
    "sequence",
    "device_time_ms",
    "mq135_raw",
    "temperature_c",
    "humidity_pct",
    "pressure_hpa",
    "latitude",
    "longitude",
    "gps_fix",
    "satellites",
}


class ConnectionState(str, Enum):
    """Lifecycle state of the serial hardware connection."""

    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"
    ERROR = "error"
    CLOSED = "closed"


@dataclass
class SerialConfig:
    """Configuration for a serial connection."""

    port: str
    baudrate: int = 9600
    timeout: float = 1.0
    reconnect: bool = True
    max_retries: int = 3
    retry_delay_s: float = 1.0
    backoff_factor: float = 2.0

    @classmethod
    def from_connection_string(
        cls,
        conn_str: str,
        default_baud: int = 9600,
        timeout: float = 1.0,
        reconnect: bool = True,
        max_retries: int = 3,
        retry_delay_s: float = 1.0,
        backoff_factor: float = 2.0,
    ) -> SerialConfig:
        """Parse a connection string into SerialConfig.

        Supports:
        - "COM3" -> port="COM3", baudrate=default_baud
        - "COM3:9600" -> port="COM3", baudrate=9600
        - "/dev/ttyUSB0" -> port="/dev/ttyUSB0", baudrate=default_baud
        - "/dev/ttyUSB0:115200" -> port="/dev/ttyUSB0", baudrate=115200
        - "serial:///dev/ttyUSB0" -> port="/dev/ttyUSB0", baudrate=default_baud
        """
        raw = conn_str.strip()
        if not raw:
            raise ValueError("Connection string cannot be empty.")

        # Strip optional "serial://" prefix
        if raw.startswith("serial://"):
            raw = raw[len("serial://") :]

        # Check for non-serial protocols
        if "://" in raw:
            scheme = raw.split("://", 1)[0]
            raise ValueError(
                f"Unsupported connection protocol: '{scheme}'. "
                "Only serial connections are supported by this adapter."
            )

        port = raw
        baud = default_baud

        # If ':' is present, check for baudrate suffix (e.g. COM3:9600 or /dev/ttyUSB0:115200)
        if ":" in raw:
            parts = raw.rsplit(":", 1)
            if parts[1].isdigit():
                port = parts[0]
                baud = int(parts[1])

        return cls(
            port=port,
            baudrate=baud,
            timeout=timeout,
            reconnect=reconnect,
            max_retries=max_retries,
            retry_delay_s=retry_delay_s,
            backoff_factor=backoff_factor,
        )


def normalize_telemetry_dict(data: dict[str, Any]) -> RawObservation:
    """Normalize a raw dictionary from firmware into a validated RawObservation.

    Maps firmware field aliases without inventing missing data,
    filters extra non-schema fields, and validates ranges through RawObservation.
    """
    normalized: dict[str, Any] = {}

    for k, v in data.items():
        canonical_key = FIELD_ALIASES.get(k, k)
        if canonical_key in CANONICAL_FIELDS:
            # Don't overwrite if canonical key was already explicitly set
            if canonical_key not in normalized or k == canonical_key:
                normalized[canonical_key] = v

    # Coerce boolean for gps_fix if received as integer or truthy value
    if "gps_fix" in normalized and not isinstance(normalized["gps_fix"], bool):
        normalized["gps_fix"] = bool(normalized["gps_fix"])

    return RawObservation(**normalized)


class SerialConnection:
    """Manages physical or mock serial communication with reconnection and frame streaming."""

    def __init__(
        self,
        config: SerialConfig,
        serial_factory: Callable[..., Any] | None = None,
        sleep_fn: Callable[[float], None] = time.sleep,
    ) -> None:
        self.config = config
        self.serial_factory = serial_factory
        self._sleep_fn = sleep_fn
        self._serial: Any | None = None
        self.state = ConnectionState.DISCONNECTED
        self.packets_received = 0
        self.packets_valid = 0
        self.packets_corrupt = 0
        self.bytes_received = 0
        self.errors_count = 0
        self.last_packet_time: datetime | None = None
        self.last_error: str | None = None

    @property
    def is_connected(self) -> bool:
        return self.state == ConnectionState.CONNECTED and self._serial is not None

    def connect(self) -> None:
        """Open the serial port connection."""
        if self.is_connected:
            return

        self.state = ConnectionState.CONNECTING
        try:
            self._open_port()
            self.state = ConnectionState.CONNECTED
            self.last_error = None
            logger.info(
                "Connected to serial port '%s' at %d baud",
                self.config.port,
                self.config.baudrate,
            )
        except Exception as e:
            self.state = ConnectionState.ERROR
            self.last_error = str(e)
            self.errors_count += 1
            logger.error("Failed to connect to serial port '%s': %s", self.config.port, e)
            raise ConnectionError(
                f"Failed to connect to serial port '{self.config.port}': {e}"
            ) from e

    def _open_port(self) -> None:
        if self.serial_factory is not None:
            self._serial = self.serial_factory(
                self.config.port,
                self.config.baudrate,
                timeout=self.config.timeout,
            )
        else:
            try:
                import serial
            except ImportError as e:
                raise ImportError(
                    "pyserial package is required for serial communication. "
                    "Install it via `pip install pyserial`."
                ) from e

            self._serial = serial.Serial(
                port=self.config.port,
                baudrate=self.config.baudrate,
                timeout=self.config.timeout,
            )

    def disconnect(self) -> None:
        """Close the serial port."""
        if self._serial is not None:
            try:
                self._serial.close()
            except Exception as e:
                logger.debug("Error while closing serial port: %s", e)
            finally:
                self._serial = None
        self.state = ConnectionState.CLOSED

    close = disconnect

    def read_line(self) -> str | None:
        """Read a single line from the serial port.

        Returns decoded line string, or None if read timed out with no data.
        """
        if not self.is_connected or self._serial is None:
            return None

        try:
            raw = self._serial.readline()
            if not raw:
                return None

            self.packets_received += 1
            self.bytes_received += len(raw)
            self.last_packet_time = datetime.now(UTC)

            if isinstance(raw, bytes):
                line = raw.decode("utf-8", errors="replace")
            else:
                line = str(raw)

            return line.strip("\r\n")
        except Exception as e:
            self.last_error = str(e)
            self.errors_count += 1
            logger.warning("Error reading from serial port '%s': %s", self.config.port, e)

            if self.config.reconnect:
                self._reconnect()
                return None

            self.state = ConnectionState.ERROR
            raise ConnectionError(
                f"Serial read error on port '{self.config.port}': {e}"
            ) from e

    def _reconnect(self) -> None:
        """Attempt exponential backoff reconnection to the serial port."""
        self.state = ConnectionState.RECONNECTING
        if self._serial is not None:
            try:
                self._serial.close()
            except Exception:
                pass
            self._serial = None

        delay = self.config.retry_delay_s
        for attempt in range(1, self.config.max_retries + 1):
            logger.info(
                "Attempting to reconnect to serial port '%s' (attempt %d/%d, delay %.1fs)...",
                self.config.port,
                attempt,
                self.config.max_retries,
                delay,
            )
            self._sleep_fn(delay)
            try:
                self._open_port()
                self.state = ConnectionState.CONNECTED
                logger.info(
                    "Successfully reconnected to serial port '%s'", self.config.port
                )
                return
            except Exception as e:
                self.last_error = str(e)
                logger.warning("Reconnect attempt %d failed: %s", attempt, e)
                delay *= self.config.backoff_factor

        self.state = ConnectionState.ERROR
        raise ConnectionError(
            f"Failed to reconnect to serial port '{self.config.port}' "
            f"after {self.config.max_retries} attempts: {self.last_error}"
        )

    def stream_lines(
        self,
        limit: int | None = None,
        max_consecutive_timeouts: int | None = None,
    ) -> Iterator[str]:
        """Yield lines continuously from the serial port.

        Args:
            limit: Maximum number of lines to yield before stopping.
            max_consecutive_timeouts: Max consecutive timeout reads before terminating stream.
        """
        if not self.is_connected:
            self.connect()

        yielded = 0
        consecutive_timeouts = 0
        while self.is_connected:
            if hasattr(self._serial, "is_open") and not self._serial.is_open:
                self.disconnect()
                break

            line = self.read_line()
            if line is not None:
                consecutive_timeouts = 0
                yield line
                yielded += 1
                if limit is not None and yielded >= limit:
                    break
            else:
                consecutive_timeouts += 1
                if (
                    max_consecutive_timeouts is not None
                    and consecutive_timeouts >= max_consecutive_timeouts
                ):
                    break

    def health(self) -> dict[str, Any]:
        """Return a diagnostics dictionary of connection health and statistics."""
        return {
            "port": self.config.port,
            "baudrate": self.config.baudrate,
            "state": self.state.value,
            "is_connected": self.is_connected,
            "packets_received": self.packets_received,
            "packets_valid": self.packets_valid,
            "packets_corrupt": self.packets_corrupt,
            "bytes_received": self.bytes_received,
            "errors_count": self.errors_count,
            "last_packet_time": (
                self.last_packet_time.isoformat() if self.last_packet_time else None
            ),
            "last_error": self.last_error,
        }

    def __enter__(self) -> SerialConnection:
        self.connect()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()


class MockSerialPort:
    """Mock serial port implementation for testing and development."""

    def __init__(
        self,
        lines: list[str | bytes] | None = None,
        raise_on_open: Exception | None = None,
        raise_on_read: Exception | None = None,
        auto_close_on_eof: bool = True,
    ) -> None:
        self.is_open = True
        self.auto_close_on_eof = auto_close_on_eof
        self.lines = [
            item.encode("utf-8") if isinstance(item, str) else item
            for item in (lines or [])
        ]
        self._index = 0
        self.raise_on_open = raise_on_open
        self.raise_on_read = raise_on_read

    def readline(self) -> bytes:
        if not self.is_open:
            return b""
        if self.raise_on_read is not None:
            exc = self.raise_on_read
            self.raise_on_read = None
            raise exc
        if self._index < len(self.lines):
            line = self.lines[self._index]
            self._index += 1
            if not line.endswith(b"\n"):
                line += b"\n"
            return line
        if self.auto_close_on_eof:
            self.is_open = False
        return b""

    def write(self, data: bytes) -> int:
        return len(data)

    def close(self) -> None:
        self.is_open = False


def list_serial_ports() -> list[dict[str, str]]:
    """Detect and return available serial COM ports on the host system.

    Uses pyserial list_ports on all platforms, with Windows registry / WMI fallback
    for maximum robustness on Windows systems.
    """
    ports: list[dict[str, str]] = []

    try:
        import serial.tools.list_ports

        for p in serial.tools.list_ports.comports():
            ports.append(
                {
                    "port": p.device,
                    "description": p.description or p.device,
                    "hwid": p.hwid or "",
                    "manufacturer": getattr(p, "manufacturer", "") or "",
                }
            )
    except Exception as e:
        logger.debug("Failed querying pyserial comports: %s", e)

    # Windows registry fallback if pyserial returned no ports
    if not ports and sys.platform == "win32":
        try:
            import winreg

            key = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DEVICEMAP\SERIALCOMM"
            )
            for i in range(winreg.QueryInfoKey(key)[1]):
                val_name, port_val, _ = winreg.EnumValue(key, i)
                port_str = str(port_val).strip()
                if port_str and not any(p["port"] == port_str for p in ports):
                    ports.append(
                        {
                            "port": port_str,
                            "description": f"{val_name} ({port_str})",
                            "hwid": "",
                            "manufacturer": "",
                        }
                    )
            winreg.CloseKey(key)
        except Exception as e:
            logger.debug("Windows registry serial scan failed: %s", e)

    return ports


class SerialManager:
    """Manages an active serial connection and background telemetry ingestion."""

    def __init__(
        self,
        on_observation: Callable[[RawObservation], Any] | None = None,
        serial_factory: Callable[..., Any] | None = None,
    ) -> None:
        self.on_observation = on_observation
        self.serial_factory = serial_factory
        self.connection: SerialConnection | None = None
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self.last_error: str | None = None

    @property
    def is_connected(self) -> bool:
        return self.connection is not None and self.connection.is_connected

    def connect(self, port: str, baudrate: int = 9600) -> dict[str, Any]:
        """Connect to a serial port and start background reader thread."""
        with self._lock:
            if self.is_connected:
                self.disconnect()

            self._stop_event.clear()
            cfg = SerialConfig(port=port.strip(), baudrate=baudrate)
            self.connection = SerialConnection(
                config=cfg, serial_factory=self.serial_factory
            )
            self.connection.connect()
            self.last_error = None

            self._thread = threading.Thread(
                target=self._reader_worker,
                daemon=True,
                name=f"burnwatch-serial-{port}",
            )
            self._thread.start()
            return self.status()

    def disconnect(self) -> dict[str, Any]:
        """Stop reader thread and close serial connection."""
        with self._lock:
            self._stop_event.set()
            if self.connection is not None:
                try:
                    self.connection.disconnect()
                except Exception as e:
                    logger.debug("Error during serial disconnect: %s", e)
            if self._thread and self._thread.is_alive():
                self._thread.join(timeout=1.5)
            self._thread = None
            return self.status()

    def _reader_worker(self) -> None:
        """Background thread target reading frames from serial and forwarding to pipeline."""
        from burnwatch.sources.cansat import CanSatLiveSource

        adapter = CanSatLiveSource(connection=self.connection)
        logger.info(
            "Serial ingestion background worker started on %s",
            self.connection.config.port if self.connection else "unknown",
        )
        while (
            not self._stop_event.is_set()
            and self.connection
            and self.connection.is_connected
        ):
            try:
                line = self.connection.read_line()
                if line is None:
                    continue
                obs = adapter.parse_frame(line)
                if obs is not None and self.on_observation:
                    self.on_observation(obs)
            except Exception as e:
                if self._stop_event.is_set():
                    break
                logger.warning("Error in serial reader thread: %s", e)
                self.last_error = str(e)
                time.sleep(0.5)

        logger.info("Serial ingestion background worker stopped.")

    def status(self) -> dict[str, Any]:
        """Return current serial connection health and telemetry metrics."""
        if self.connection is not None:
            data = self.connection.health()
            data["background_reader_active"] = bool(
                self._thread and self._thread.is_alive()
            )
            if self.last_error and not data.get("last_error"):
                data["last_error"] = self.last_error
            return data
        return {
            "port": None,
            "baudrate": None,
            "state": ConnectionState.DISCONNECTED.value,
            "is_connected": False,
            "packets_received": 0,
            "packets_valid": 0,
            "packets_corrupt": 0,
            "bytes_received": 0,
            "errors_count": 0,
            "last_packet_time": None,
            "last_error": self.last_error,
            "background_reader_active": False,
        }
