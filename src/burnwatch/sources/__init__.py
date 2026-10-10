"""Observation sources for BurnWatch.

Includes simulator, recorded replay, and live hardware serial adapters.
"""

from __future__ import annotations

from burnwatch.sources.base import ObservationSource
from burnwatch.sources.cansat import CanSatLiveSource, CanSatReplaySource
from burnwatch.sources.serial import (
    ConnectionState,
    MockSerialPort,
    SerialConfig,
    SerialConnection,
    SerialManager,
    list_serial_ports,
    normalize_telemetry_dict,
)
from burnwatch.sources.simulator import SimulatorScenario, SimulatorSource

__all__ = [
    "CanSatLiveSource",
    "CanSatReplaySource",
    "ConnectionState",
    "MockSerialPort",
    "ObservationSource",
    "SerialConfig",
    "SerialConnection",
    "SerialManager",
    "SimulatorScenario",
    "SimulatorSource",
    "list_serial_ports",
    "normalize_telemetry_dict",
]
