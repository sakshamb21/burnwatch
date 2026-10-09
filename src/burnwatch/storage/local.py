"""Local SQLite storage backend for BurnWatch.

Implements persistent storage for observations, quality flags, incidents,
audit history, and community reports. Ensures idempotent ingestion through
device_id + sequence uniqueness.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from burnwatch.incidents.models import (
    Incident,
    IncidentHistoryEntry,
    IncidentStatus,
)
from burnwatch.models.observation import (
    NormalizedObservation,
    QualityFlag,
    SourceMode,
)
from burnwatch.storage.base import StorageBackend

logger = logging.getLogger(__name__)


def _to_iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.isoformat()


def _from_iso(dt_str: str | None) -> datetime | None:
    if not dt_str:
        return None
    return datetime.fromisoformat(dt_str)


class LocalStorage(StorageBackend):
    """SQLite implementation of StorageBackend.

    Thread-safe connection handling with composite uniqueness constraint
    on (device_id, sequence) to guarantee idempotency.
    """

    def __init__(self, db_path: Path | str = ":memory:") -> None:
        self.db_path = str(db_path)
        if self.db_path != ":memory:":
            path_obj = Path(self.db_path)
            path_obj.parent.mkdir(parents=True, exist_ok=True)

        self._conn = sqlite3.connect(
            self.db_path,
            check_same_thread=False,
            isolation_level=None,  # Autocommit mode, we manage transactions explicitly
        )
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        with self._conn:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS observations (
                    observation_id TEXT PRIMARY KEY,
                    device_id TEXT NOT NULL,
                    sequence INTEGER NOT NULL,
                    device_time_ms INTEGER NOT NULL,
                    mq135_raw INTEGER NOT NULL,
                    temperature_c REAL,
                    humidity_pct REAL,
                    pressure_hpa REAL,
                    latitude REAL,
                    longitude REAL,
                    gps_fix INTEGER NOT NULL,
                    satellites INTEGER NOT NULL,
                    source_mode TEXT NOT NULL,
                    is_simulated INTEGER NOT NULL,
                    received_at TEXT NOT NULL,
                    raw_payload TEXT,
                    anomaly_score REAL,
                    anomaly_detected INTEGER NOT NULL,
                    schema_version INTEGER NOT NULL DEFAULT 1,
                    UNIQUE(device_id, sequence)
                );

                CREATE TABLE IF NOT EXISTS quality_flags (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    observation_id TEXT NOT NULL,
                    flag TEXT NOT NULL,
                    FOREIGN KEY(observation_id) REFERENCES observations(observation_id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS incidents (
                    incident_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    device_id TEXT NOT NULL,
                    source_mode TEXT NOT NULL,
                    is_simulated INTEGER NOT NULL,
                    trigger_observation_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    latitude REAL,
                    longitude REAL,
                    peak_mq135 INTEGER NOT NULL,
                    peak_anomaly_score REAL NOT NULL,
                    reviewer TEXT,
                    notes TEXT
                );

                CREATE TABLE IF NOT EXISTS incident_history (
                    entry_id TEXT PRIMARY KEY,
                    incident_id TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    from_status TEXT NOT NULL,
                    to_status TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    notes TEXT NOT NULL,
                    FOREIGN KEY(incident_id) REFERENCES incidents(incident_id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS incident_observations (
                    incident_id TEXT NOT NULL,
                    observation_id TEXT NOT NULL,
                    PRIMARY KEY(incident_id, observation_id),
                    FOREIGN KEY(incident_id) REFERENCES incidents(incident_id) ON DELETE CASCADE,
                    FOREIGN KEY(observation_id) REFERENCES observations(observation_id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS community_reports (
                    report_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    reporter_name TEXT NOT NULL,
                    contact TEXT,
                    latitude REAL,
                    longitude REAL,
                    description TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'submitted'
                );

                CREATE INDEX IF NOT EXISTS idx_obs_device_seq ON observations(device_id, sequence);
                CREATE INDEX IF NOT EXISTS idx_obs_received ON observations(received_at);
                CREATE INDEX IF NOT EXISTS idx_incidents_status ON incidents(status);
                CREATE INDEX IF NOT EXISTS idx_inc_hist_inc ON incident_history(incident_id);
                """
            )

    def close(self) -> None:
        """Close database connection."""
        self._conn.close()

    def _row_to_observation(self, row: sqlite3.Row) -> NormalizedObservation:
        obs_id = row["observation_id"]
        # Fetch quality flags
        flags_cursor = self._conn.execute(
            "SELECT flag FROM quality_flags WHERE observation_id = ?",
            (obs_id,),
        )
        flags = [QualityFlag(f_row["flag"]) for f_row in flags_cursor.fetchall()]

        return NormalizedObservation(
            observation_id=obs_id,
            schema_version=row["schema_version"],
            source_mode=SourceMode(row["source_mode"]),
            is_simulated=bool(row["is_simulated"]),
            received_at=_from_iso(row["received_at"]) or datetime.now(UTC),
            device_id=row["device_id"],
            sequence=row["sequence"],
            device_time_ms=row["device_time_ms"],
            mq135_raw=row["mq135_raw"],
            temperature_c=row["temperature_c"],
            humidity_pct=row["humidity_pct"],
            pressure_hpa=row["pressure_hpa"],
            latitude=row["latitude"],
            longitude=row["longitude"],
            gps_fix=bool(row["gps_fix"]),
            satellites=row["satellites"],
            raw_payload=row["raw_payload"],
            quality_flags=flags,
            anomaly_score=row["anomaly_score"],
            anomaly_detected=bool(row["anomaly_detected"]),
        )

    def save_observation(
        self, obs: NormalizedObservation
    ) -> tuple[NormalizedObservation, bool]:
        """Save a normalized observation idempotently."""
        # Check if already present by (device_id, sequence)
        existing = self.get_observation_by_sequence(obs.device_id, obs.sequence)
        if existing is not None:
            return existing, False

        with self._conn:
            self._conn.execute(
                """
                INSERT INTO observations (
                    observation_id, device_id, sequence, device_time_ms, mq135_raw,
                    temperature_c, humidity_pct, pressure_hpa, latitude, longitude,
                    gps_fix, satellites, source_mode, is_simulated, received_at,
                    raw_payload, anomaly_score, anomaly_detected, schema_version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    obs.observation_id,
                    obs.device_id,
                    obs.sequence,
                    obs.device_time_ms,
                    obs.mq135_raw,
                    obs.temperature_c,
                    obs.humidity_pct,
                    obs.pressure_hpa,
                    obs.latitude,
                    obs.longitude,
                    1 if obs.gps_fix else 0,
                    obs.satellites,
                    obs.source_mode.value,
                    1 if obs.is_simulated else 0,
                    _to_iso(obs.received_at),
                    obs.raw_payload,
                    obs.anomaly_score,
                    1 if obs.anomaly_detected else 0,
                    obs.schema_version,
                ),
            )
            for flag in obs.quality_flags:
                self._conn.execute(
                    "INSERT INTO quality_flags (observation_id, flag) VALUES (?, ?)",
                    (obs.observation_id, flag.value),
                )

        return obs, True

    def get_observation(self, observation_id: str) -> NormalizedObservation | None:
        cursor = self._conn.execute(
            "SELECT * FROM observations WHERE observation_id = ?",
            (observation_id,),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return self._row_to_observation(row)

    def get_observation_by_sequence(
        self, device_id: str, sequence: int
    ) -> NormalizedObservation | None:
        cursor = self._conn.execute(
            "SELECT * FROM observations WHERE device_id = ? AND sequence = ?",
            (device_id, sequence),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return self._row_to_observation(row)

    def list_observations(
        self,
        device_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[NormalizedObservation], int]:
        if device_id:
            count_cursor = self._conn.execute(
                "SELECT COUNT(*) FROM observations WHERE device_id = ?",
                (device_id,),
            )
            total = count_cursor.fetchone()[0]
            cursor = self._conn.execute(
                """
                SELECT * FROM observations
                WHERE device_id = ?
                ORDER BY received_at DESC, sequence DESC
                LIMIT ? OFFSET ?
                """,
                (device_id, limit, offset),
            )
        else:
            count_cursor = self._conn.execute("SELECT COUNT(*) FROM observations")
            total = count_cursor.fetchone()[0]
            cursor = self._conn.execute(
                """
                SELECT * FROM observations
                ORDER BY received_at DESC, sequence DESC
                LIMIT ? OFFSET ?
                """,
                (limit, offset),
            )

        items = [self._row_to_observation(row) for row in cursor.fetchall()]
        return items, total

    def _row_to_incident(self, row: sqlite3.Row) -> Incident:
        inc_id = row["incident_id"]

        # Fetch history
        hist_cursor = self._conn.execute(
            "SELECT * FROM incident_history WHERE incident_id = ? ORDER BY timestamp ASC",
            (inc_id,),
        )
        history = [
            IncidentHistoryEntry(
                entry_id=h_row["entry_id"],
                timestamp=_from_iso(h_row["timestamp"]) or datetime.now(UTC),
                from_status=IncidentStatus(h_row["from_status"]),
                to_status=IncidentStatus(h_row["to_status"]),
                actor=h_row["actor"],
                notes=h_row["notes"],
            )
            for h_row in hist_cursor.fetchall()
        ]

        # Fetch observation_ids
        obs_cursor = self._conn.execute(
            "SELECT observation_id FROM incident_observations WHERE incident_id = ?",
            (inc_id,),
        )
        obs_ids = [o_row["observation_id"] for o_row in obs_cursor.fetchall()]

        return Incident(
            incident_id=inc_id,
            status=IncidentStatus(row["status"]),
            device_id=row["device_id"],
            source_mode=SourceMode(row["source_mode"]),
            is_simulated=bool(row["is_simulated"]),
            trigger_observation_id=row["trigger_observation_id"],
            created_at=_from_iso(row["created_at"]) or datetime.now(UTC),
            updated_at=_from_iso(row["updated_at"]) or datetime.now(UTC),
            latitude=row["latitude"],
            longitude=row["longitude"],
            peak_mq135=row["peak_mq135"],
            peak_anomaly_score=row["peak_anomaly_score"],
            reviewer=row["reviewer"],
            notes=row["notes"],
            observation_ids=obs_ids,
            history=history,
        )

    def save_incident(self, incident: Incident) -> None:
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO incidents (
                    incident_id, status, device_id, source_mode, is_simulated,
                    trigger_observation_id, created_at, updated_at, latitude, longitude,
                    peak_mq135, peak_anomaly_score, reviewer, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(incident_id) DO UPDATE SET
                    status=excluded.status,
                    updated_at=excluded.updated_at,
                    reviewer=excluded.reviewer,
                    notes=excluded.notes,
                    peak_mq135=excluded.peak_mq135,
                    peak_anomaly_score=excluded.peak_anomaly_score
                """,
                (
                    incident.incident_id,
                    incident.status.value,
                    incident.device_id,
                    incident.source_mode.value,
                    1 if incident.is_simulated else 0,
                    incident.trigger_observation_id,
                    _to_iso(incident.created_at),
                    _to_iso(incident.updated_at),
                    incident.latitude,
                    incident.longitude,
                    incident.peak_mq135,
                    incident.peak_anomaly_score,
                    incident.reviewer,
                    incident.notes,
                ),
            )

            # Insert history entries (INSERT OR IGNORE by entry_id)
            for entry in incident.history:
                self._conn.execute(
                    """
                    INSERT OR IGNORE INTO incident_history (
                        entry_id, incident_id, timestamp, from_status, to_status, actor, notes
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        entry.entry_id,
                        incident.incident_id,
                        _to_iso(entry.timestamp),
                        entry.from_status.value,
                        entry.to_status.value,
                        entry.actor,
                        entry.notes,
                    ),
                )

            # Insert observation associations
            for obs_id in incident.observation_ids:
                self._conn.execute(
                    """
                    INSERT OR IGNORE INTO incident_observations (
                        incident_id, observation_id
                    ) VALUES (?, ?)
                    """,
                    (incident.incident_id, obs_id),
                )

    def get_incident(self, incident_id: str) -> Incident | None:
        cursor = self._conn.execute(
            "SELECT * FROM incidents WHERE incident_id = ?",
            (incident_id,),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return self._row_to_incident(row)

    def list_incidents(
        self,
        status: IncidentStatus | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[Incident], int]:
        if status is not None:
            status_val = (
                status.value if isinstance(status, IncidentStatus) else str(status)
            )
            count_cursor = self._conn.execute(
                "SELECT COUNT(*) FROM incidents WHERE status = ?",
                (status_val,),
            )
            total = count_cursor.fetchone()[0]
            cursor = self._conn.execute(
                """
                SELECT * FROM incidents
                WHERE status = ?
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?
                """,
                (status_val, limit, offset),
            )
        else:
            count_cursor = self._conn.execute("SELECT COUNT(*) FROM incidents")
            total = count_cursor.fetchone()[0]
            cursor = self._conn.execute(
                """
                SELECT * FROM incidents
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?
                """,
                (limit, offset),
            )

        items = [self._row_to_incident(row) for row in cursor.fetchall()]
        return items, total

    def save_community_report(
        self,
        report_id: str,
        reporter_name: str,
        description: str,
        contact: str | None = None,
        latitude: float | None = None,
        longitude: float | None = None,
    ) -> dict[str, Any]:
        """Save a community-submitted incident report."""
        created_at = datetime.now(UTC).isoformat()
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO community_reports (
                    report_id, created_at, reporter_name, contact, latitude, longitude, description, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'submitted')
                """,
                (
                    report_id,
                    created_at,
                    reporter_name,
                    contact,
                    latitude,
                    longitude,
                    description,
                ),
            )
        return {
            "report_id": report_id,
            "created_at": created_at,
            "reporter_name": reporter_name,
            "description": description,
            "status": "submitted",
        }
