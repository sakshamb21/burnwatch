"""FastAPI REST API for BurnWatch.

Provides endpoints for observation ingestion, history queries, incident management,
and community reports.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query, status
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from burnwatch.config.settings import get_settings
from burnwatch.incidents.models import (
    IncidentStatus,
    InvalidTransitionError,
)
from burnwatch.incidents.service import IncidentService
from burnwatch.models.observation import (
    RawObservation,
    SourceMode,
)
from burnwatch.pipeline.processor import PipelineProcessor
from burnwatch.sources.serial import (
    SerialManager,
    list_serial_ports,
)
from burnwatch.storage.base import StorageBackend
from burnwatch.storage.local import LocalStorage

STATIC_DIR = Path(__file__).parent / "static"


class SerialConnectRequest(BaseModel):
    """Payload for establishing live serial connection."""

    port: str = Field(..., min_length=1, description="Serial port identifier (e.g. COM5)")
    baudrate: int = Field(9600, ge=300, le=921600, description="Serial baudrate")


class ReviewRequest(BaseModel):
    """Payload for incident human review."""

    reviewer: str = Field(..., min_length=1, description="Officer or reviewer name")
    action: str = Field(..., description="'confirm', 'dismiss', or 'under_review'")
    notes: str = Field(..., min_length=1, description="Justification notes")


class StatusUpdateRequest(BaseModel):
    """Payload for updating incident status."""

    status: IncidentStatus = Field(..., description="Target status")
    reviewer: str = Field(..., min_length=1, description="Officer or reviewer name")
    notes: str = Field(..., min_length=1, description="Reason for status update")


class CommunityReportRequest(BaseModel):
    """Payload for community incident report."""

    reporter_name: str = Field(..., min_length=1)
    description: str = Field(..., min_length=1)
    contact: str | None = None
    latitude: float | None = None
    longitude: float | None = None


def create_app(
    storage: StorageBackend | None = None,
    incident_service: IncidentService | None = None,
    processor: PipelineProcessor | None = None,
    serial_manager: SerialManager | None = None,
) -> FastAPI:
    """Create and configure the FastAPI application instance."""
    from burnwatch.config.settings import StorageBackend as _SB  # noqa: PLC0415, N814

    settings = get_settings()

    if storage is not None:
        db = storage
    elif settings.storage_backend == _SB.AWS:
        from burnwatch.aws.adapter import AWSStorageAdapter  # noqa: PLC0415

        db = AWSStorageAdapter(
            s3_bucket=settings.aws_s3_bucket,
            dynamodb_table=settings.aws_dynamodb_table,
            region=settings.aws_region,
        )
    else:
        db = LocalStorage(settings.database_path)

    service = incident_service or IncidentService(storage=db)
    pipe = processor or PipelineProcessor(
        storage=db,
        incident_service=service,
        source_mode=(
            SourceMode.CANSAT
            if settings.data_source.value == "cansat"
            else SourceMode.SIMULATED
        ),
    )

    app = FastAPI(
        title="BurnWatch",
        version="0.1.0",
        description="CanSat-Assisted Environmental Incident Investigation System",
    )

    @app.get("/", include_in_schema=False)
    def frontend() -> FileResponse:
        """Serve the temporary local operations dashboard."""
        return FileResponse(STATIC_DIR / "index.html")

    def _ingest_live_telemetry(raw: RawObservation) -> None:
        raw.source_mode = SourceMode.CANSAT
        raw.is_simulated = False
        pipe.process_raw(raw=raw)

    serial_mgr = serial_manager or SerialManager(
        on_observation=_ingest_live_telemetry
    )

    @app.get("/health")
    def health_check() -> dict[str, Any]:
        """System health and configuration summary."""
        mgr_status = serial_mgr.status()
        is_conn = mgr_status.get("is_connected", False)
        return {
            "status": "healthy",
            "version": "0.1.0",
            "data_source": "cansat" if is_conn else settings.data_source.value,
            "storage": settings.storage_backend.value,
            "telemetry": {
                "configured": bool(settings.cansat_source or is_conn),
                "source": mgr_status.get("port") or settings.cansat_source or None,
                "baud": mgr_status.get("baudrate") or settings.cansat_baud,
                "is_connected": is_conn,
            },
        }

    @app.get("/telemetry/status")
    def telemetry_status() -> dict[str, Any]:
        """Hardware telemetry connection health and freshness status."""
        source_cfg = settings.cansat_source
        mgr_status = serial_mgr.status()
        is_conn = mgr_status.get("is_connected", False)
        return {
            "configured": bool(source_cfg or is_conn),
            "status": "connected" if is_conn else ("configured" if source_cfg else "unconfigured"),
            "source": mgr_status.get("port") or source_cfg or None,
            "baud": mgr_status.get("baudrate") or settings.cansat_baud,
            "data_source_mode": settings.data_source.value,
            "serial": mgr_status,
        }

    @app.get("/serial/ports")
    def get_serial_ports() -> dict[str, Any]:
        """Detect and return available serial COM ports on the host system."""
        return {"ports": list_serial_ports()}

    @app.get("/serial/status")
    def get_serial_status() -> dict[str, Any]:
        """Get live serial connection metrics and health."""
        return serial_mgr.status()

    @app.post("/serial/connect")
    def connect_serial(body: SerialConnectRequest) -> dict[str, Any]:
        """Connect to CanSat serial port receiver."""
        try:
            return serial_mgr.connect(port=body.port, baudrate=body.baudrate)
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Failed to connect to serial port '{body.port}': {e}",
            )

    @app.post("/serial/disconnect")
    @app.delete("/serial/connect")
    def disconnect_serial() -> dict[str, Any]:
        """Disconnect CanSat serial port receiver."""
        return serial_mgr.disconnect()

    @app.post(
        "/observations",
        status_code=status.HTTP_201_CREATED,
        response_model=None,
    )
    def submit_observation(payload: RawObservation) -> JSONResponse:
        """Submit a single raw observation for ingestion.

        Idempotent: Re-submitting the same observation returns the existing record.
        """
        result = pipe.process_raw(raw=payload)
        resp_status = status.HTTP_201_CREATED if result.is_new else status.HTTP_200_OK
        return JSONResponse(
            status_code=resp_status,
            content={
                "observation_id": result.observation.observation_id,
                "status": "accepted" if result.is_new else "duplicate_accepted",
                "source_mode": result.observation.source_mode.value,
                "is_simulated": result.observation.is_simulated,
                "quality_flags": [f.value for f in result.quality_flags],
                "anomaly_detected": result.observation.anomaly_detected,
                "anomaly_score": result.observation.anomaly_score,
                "candidate_incident_id": (
                    result.candidate_incident.incident_id
                    if result.candidate_incident
                    else None
                ),
            },
        )

    @app.get("/observations")
    def list_observations(
        device_id: str | None = Query(None, description="Filter by device ID"),
        limit: int = Query(50, ge=1, le=500),
        offset: int = Query(0, ge=0),
    ) -> dict[str, Any]:
        """Query stored observations with optional device filtering and pagination."""
        items, total = db.list_observations(
            device_id=device_id, limit=limit, offset=offset
        )
        return {
            "items": [item.model_dump(mode="json") for item in items],
            "total": total,
            "limit": limit,
            "offset": offset,
        }

    @app.get("/incidents")
    def list_incidents(
        status_filter: IncidentStatus | None = Query(
            None, alias="status", description="Filter by status"
        ),
        limit: int = Query(20, ge=1, le=100),
        offset: int = Query(0, ge=0),
    ) -> dict[str, Any]:
        """List incidents with status filtering and pagination."""
        items, total = service.list_incidents(
            status=status_filter, limit=limit, offset=offset
        )
        return {
            "items": [item.model_dump(mode="json") for item in items],
            "total": total,
            "limit": limit,
            "offset": offset,
        }

    @app.get("/incidents/{incident_id}")
    def get_incident(incident_id: str) -> dict[str, Any]:
        """Retrieve full details of an incident including complete audit history."""
        inc = service.get_incident(incident_id)
        if inc is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Incident not found",
            )
        return inc.model_dump(mode="json")

    @app.post("/incidents/{incident_id}/review")
    def review_incident(
        incident_id: str,
        body: ReviewRequest,
    ) -> dict[str, Any]:
        """Review an incident ('under_review', 'confirm', or 'dismiss')."""
        try:
            inc = service.review_incident(
                incident_id=incident_id,
                action=body.action,
                reviewer=body.reviewer,
                notes=body.notes,
            )
            return inc.model_dump(mode="json")
        except KeyError:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Incident not found",
            )
        except InvalidTransitionError as e:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(e),
            )
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(e),
            )

    @app.post("/incidents/{incident_id}/status")
    def update_incident_status(
        incident_id: str,
        body: StatusUpdateRequest,
    ) -> dict[str, Any]:
        """Update incident lifecycle status."""
        try:
            inc = service.update_status(
                incident_id=incident_id,
                new_status=body.status,
                actor=body.reviewer,
                notes=body.notes,
            )
            return inc.model_dump(mode="json")
        except KeyError:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Incident not found",
            )
        except InvalidTransitionError as e:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(e),
            )

    @app.post(
        "/reports",
        status_code=status.HTTP_201_CREATED,
    )
    def submit_community_report(
        body: CommunityReportRequest,
    ) -> dict[str, Any]:
        """Submit an optional community report of suspected burning."""
        report_id = str(uuid.uuid4())
        if isinstance(db, LocalStorage):
            return db.save_community_report(
                report_id=report_id,
                reporter_name=body.reporter_name,
                description=body.description,
                contact=body.contact,
                latitude=body.latitude,
                longitude=body.longitude,
            )
        return {"report_id": report_id, "status": "submitted"}

    # Deliberately dependency-free frontend assets. API routes above take
    # precedence over this mount, so the page and the REST interface share one
    # local server during the prototype phase.
    app.mount(
        "/static",
        StaticFiles(directory=STATIC_DIR),
        name="frontend-static",
    )

    return app


# Default ASGI app instance
app = create_app()
