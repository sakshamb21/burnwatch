"""End-to-End integration tests for BurnWatch workflows.

Exercises full workflows:
1. Simulated pipeline flow with simulation isolation enforcement
2. Real/Replay CanSat flow with full incident lifecycle to resolution
3. Idempotent re-execution and data integrity
"""

from __future__ import annotations

import json
from pathlib import Path

from starlette.testclient import TestClient

from burnwatch.api.app import create_app
from burnwatch.incidents.service import IncidentService
from burnwatch.models.observation import SourceMode
from burnwatch.pipeline.processor import PipelineProcessor
from burnwatch.sources.simulator import SimulatorScenario, SimulatorSource
from burnwatch.storage.local import LocalStorage


class TestEndToEndSimulatedFlow:
    """T-120: E2E Simulated pipeline flow."""

    def test_e2e_simulation_to_dismissal(self, tmp_path: Path) -> None:
        db_path = tmp_path / "sim_e2e.db"
        storage = LocalStorage(db_path)
        service = IncidentService(storage=storage)
        processor = PipelineProcessor(storage=storage, incident_service=service)

        # 1. Generate sustained anomaly synthetic stream
        sim = SimulatorSource(
            scenario=SimulatorScenario.SUSTAINED_ANOMALY,
            seed=42,
            count=80,
            interval_ms=1000,
        )

        # 2. Process observations into storage
        summary = processor.process_source(sim)
        assert summary.total_received == 80
        assert summary.anomalies_detected > 0
        assert summary.incidents_created >= 1

        # 3. Verify incidents via REST API
        app = create_app(storage=storage, incident_service=service)
        client = TestClient(app)

        incidents_resp = client.get("/incidents?status=candidate")
        assert incidents_resp.status_code == 200
        inc_data = incidents_resp.json()
        assert inc_data["total"] >= 1
        target_incident = inc_data["items"][0]
        inc_id = target_incident["incident_id"]
        assert target_incident["is_simulated"] is True

        # 4. Attempt to confirm simulated incident -> MUST be rejected with 409 Conflict
        confirm_resp = client.post(
            f"/incidents/{inc_id}/review",
            json={
                "action": "confirm",
                "reviewer": "Officer Smith",
                "notes": "Testing confirmation on simulation",
            },
        )
        assert confirm_resp.status_code == 409
        assert (
            "Simulated incidents cannot be confirmed" in confirm_resp.json()["detail"]
        )

        # 5. Dismiss simulated incident -> Allowed
        dismiss_resp = client.post(
            f"/incidents/{inc_id}/review",
            json={
                "action": "dismiss",
                "reviewer": "Officer Smith",
                "notes": "Dismissing synthetic training incident",
            },
        )
        assert dismiss_resp.status_code == 200
        assert dismiss_resp.json()["status"] == "dismissed"

        # 6. Verify audit history contains transition details
        get_resp = client.get(f"/incidents/{inc_id}")
        assert get_resp.status_code == 200
        hist = get_resp.json()["history"]
        assert any(h["to_status"] == "dismissed" for h in hist)
        assert any(h["actor"] == "Officer Smith" for h in hist)


class TestEndToEndCanSatReplayFlow:
    """T-121: E2E Recorded CanSat replay flow with confirmation and resolution."""

    def test_e2e_cansat_full_lifecycle(
        self, tmp_path: Path, canonical_obs: dict
    ) -> None:
        db_path = tmp_path / "cansat_e2e.db"
        replay_file = tmp_path / "cansat_recording.jsonl"

        # Create 60 observations: 45 baseline readings (10 warmup + 35 baseline),
        # then 5 elevated readings (750), then normal
        records = []
        for seq in range(1, 61):
            mq135_val = 750 if 46 <= seq <= 50 else 300
            obs_dict = {
                **canonical_obs,
                "sequence": seq,
                "device_time_ms": seq * 2000,
                "mq135_raw": mq135_val,
            }
            records.append(json.dumps(obs_dict))

        replay_file.write_text("\n".join(records) + "\n", encoding="utf-8")

        storage = LocalStorage(db_path)
        service = IncidentService(storage=storage)
        processor = PipelineProcessor(
            storage=storage,
            incident_service=service,
            source_mode=SourceMode.CANSAT,
        )

        # 1. Run replay through pipeline
        summary = processor.process_file(replay_file, source_mode=SourceMode.CANSAT)
        assert summary.total_received == 60
        assert summary.new_observations == 60
        assert summary.incidents_created >= 1

        # 2. Connect API
        app = create_app(storage=storage, incident_service=service)
        client = TestClient(app)

        inc_list = client.get("/incidents?status=candidate").json()
        assert inc_list["total"] >= 1
        incident = inc_list["items"][0]
        inc_id = incident["incident_id"]
        assert incident["source_mode"] == "cansat"
        assert incident["is_simulated"] is False

        # 3. Confirm incident via review
        confirm_resp = client.post(
            f"/incidents/{inc_id}/review",
            json={
                "action": "confirm",
                "reviewer": "Inspector Roy",
                "notes": "Field patrol confirmed burning waste pile at coordinates",
            },
        )
        assert confirm_resp.status_code == 200
        assert confirm_resp.json()["status"] == "confirmed"

        # 4. Resolve incident
        resolve_resp = client.post(
            f"/incidents/{inc_id}/status",
            json={
                "status": "resolved",
                "reviewer": "Inspector Roy",
                "notes": "Fire extinguished by community response team",
            },
        )
        assert resolve_resp.status_code == 200
        assert resolve_resp.json()["status"] == "resolved"

        # 5. Move to monitoring
        mon_resp = client.post(
            f"/incidents/{inc_id}/status",
            json={
                "status": "monitoring",
                "reviewer": "Inspector Roy",
                "notes": "Drone monitoring site for 12 hours",
            },
        )
        assert mon_resp.status_code == 200
        assert mon_resp.json()["status"] == "monitoring"

        # 6. Final resolution
        final_resp = client.post(
            f"/incidents/{inc_id}/status",
            json={
                "status": "resolved",
                "reviewer": "Inspector Roy",
                "notes": "No smoke detected, site cleared",
            },
        )
        assert final_resp.status_code == 200
        assert final_resp.json()["status"] == "resolved"

        # 7. Test Idempotency: Replaying the file again produces 0 new records
        replay_summary_2 = processor.process_file(
            replay_file, source_mode=SourceMode.CANSAT
        )
        assert replay_summary_2.total_received == 60
        assert replay_summary_2.new_observations == 0
        assert replay_summary_2.duplicates == 60
        assert replay_summary_2.incidents_created == 0
